"""Causal, explicitly approximate sweep factors and symmetric perpetual accounting."""
from pathlib import Path
from functools import lru_cache
import sys, math, hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'rotation-leverage-v1'))
import rotation_engine as old
base=old.base
SYMBOLS=('BTCUSDT','ETHUSDT')
NAMES={'long_control':'原30日动量 · 只做多','momentum_ls':'30日动量 · 多空','sweep_ls':'扫高低点收回 · 多空近似','sweep_trend':'扫高低点收回 + 动量方向'}
SCENARIOS=old.SCENARIOS

def sweep_factors(raw):
    """Index is signal availability time (close), not bar-open timestamp."""
    h=raw.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    complete=raw.close.resample('1h').count().eq(12)&raw.volume.gt(0).resample('1h').sum().eq(12)
    h.loc[~complete,['open','high','low','close']]=np.nan
    hh=h.high.shift(1).rolling(24,min_periods=24).max();ll=h.low.shift(1).rolling(24,min_periods=24).min()
    # Most recent extreme matters for equal highs/lows; all 24 bars precede signal.
    highage=h.high.shift(1).rolling(24,min_periods=24).apply(lambda a:24-np.flatnonzero(a==np.max(a))[-1],raw=True)
    lowage=h.low.shift(1).rolling(24,min_periods=24).apply(lambda a:24-np.flatnonzero(a==np.min(a))[-1],raw=True)
    tr=pd.concat([h.high-h.low,(h.high-h.close.shift(1)).abs(),(h.low-h.close.shift(1)).abs()],axis=1).max(axis=1)
    atr=tr.where(complete).shift(1).rolling(14,min_periods=14).mean()
    buy=(h.low<ll)&(h.close>ll)&lowage.ge(6)&atr.gt(0)
    sell=(h.high>hh)&(h.close<hh)&highage.ge(6)&atr.gt(0)
    direction=np.where(buy&~sell,1,np.where(sell&~buy,-1,0))
    score=np.where(direction==1,(h.close-ll)/atr,np.where(direction==-1,(h.close-hh)/atr,0))
    r=pd.DataFrame({'direction':direction,'score':score,'prior_high':hh,'prior_low':ll,'high_age':highage,'low_age':lowage,'prior_atr':atr,'close':h.close})
    r.index=r.index+pd.Timedelta(hours=1)
    return r

@lru_cache(maxsize=1)
def all_factors():return {s:sweep_factors(old.load_frame('perp',s,'klines')) for s in SYMBOLS}

@lru_cache(maxsize=6)
def prepare(start,end,delay=0):
    ix=pd.date_range(pd.Timestamp(start,tz='UTC'),pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1),freq='5min',inclusive='left')
    px={};mk={};rates={};ok={};avail={};signals={};mom={};budgets={};daily=old.prior.old.rankings()[0]
    info=ix-pd.Timedelta(minutes=delay)
    decision=(info.minute==0)&(info.second==0)&(info>=pd.Timestamp(start,tz='UTC'))
    days=info.normalize()-pd.Timedelta(days=1)
    for s in SYMBOLS:
        d=old.load_frame('perp',s,'klines');m=old.load_frame('perp',s,'markPriceKlines');fd=old.load_frame('perp',s,'fundingRate')
        px[s]=d.reindex(ix)[['open','high','low','close','volume']].to_numpy(float)
        mk[s]=m.reindex(ix)[['open','high','low','close']].to_numpy(float)
        pre=d.reindex(ix-pd.Timedelta(minutes=5));prem=m.reindex(ix-pd.Timedelta(minutes=5))
        avail[s]=np.where(pre.volume.gt(0)&pre.close.gt(0),np.where(prem.close.gt(0),1,2),0)
        rates[s]=fd.last_funding_rate.reindex(ix).fillna(0).to_numpy(float)
        valid=np.zeros(len(ix),bool)
        for when,row in fd.iterrows():
            lo=ix.searchsorted(when-pd.Timedelta(hours=float(row.funding_interval_hours)));hi=ix.searchsorted(when,side='right');valid[lo:hi]=True
        if len(fd):
            lo=ix.searchsorted(fd.index[-1]);hi=ix.searchsorted(fd.index[-1]+pd.Timedelta(hours=float(fd.funding_interval_hours.iloc[-1])));valid[lo:hi]=True
        valid&=np.array([x.strftime('%Y-%m') in old.manifest()['availability'][s]['fundingRate'] for x in ix]);ok[s]=valid
        signals[s]=all_factors()[s].direction.reindex(info).fillna(0).to_numpy(int)
        q=daily[s].reindex(days);v=q['valid'].fillna(False).to_numpy(bool)&np.isfinite(q.mom.to_numpy(float))
        mom[s]=np.where(v,np.sign(q.mom.to_numpy(float)),0).astype(int)
        sigma=q.sigma.to_numpy(float);budgets[s]=np.where(v&np.isfinite(sigma)&(sigma>0),np.minimum(200,2/np.maximum(sigma,1e-9)),0)
    return dict(index=ix,px=px,mk=mk,rates=rates,ok=ok,avail=avail,signals=signals,mom=mom,budgets=budgets,decision=np.array(decision))

def simulate(start,end,mode,leverage=1,fee=.001,delay=0,fixture=None):
    assert mode in NAMES and leverage in range(1,11) and delay in (0,5)
    z=fixture if fixture is not None else prepare(start,end,delay)
    ix=z['index'];tslist=ix.as_unit('s').asi8;px=z['px'];mk=z['mk'];rates=z['rates'];slip=.0005
    cash=1000.;pos={};cool={};stops=[];guard=0;peak=1000.;ddmax=0.;mincash=1000.;minratio=1e9;stressdd=0.;maxexp=0.;sumexp=0.;equity=1000.
    orders=[];trades=[];events=[];issues=[];curve=[[int(tslist[0]),1000.,0.,0.]];blocked=0
    def close(s,ref,ts,reason,info):
        nonlocal cash,guard
        p=pos.pop(s);side=p['side'];fill=ref*(1-side*slip);exitfee=p['qty']*fill*fee
        pnl=side*p['qty']*(fill-p['fill']);net=pnl-p['entryfee']-exitfee-p['funding']
        cash+=p['margin']+pnl-exitfee-p['funding'];slippage=p['qty']*(abs(p['fill']-p['ref'])+abs(ref-fill))
        trades.append(dict(symbol=s,direction='long' if side==1 else 'short',entry_ts=p['ts'],exit_ts=int(ts),entry_price=p['fill'],exit_price=fill,entry_reference=p['ref'],exit_reference=ref,qty=p['qty'],margin=p['margin'],notional=p['margin']*leverage,pnl=net,gross_pnl=net+p['entryfee']+exitfee+slippage+p['funding'],fees=p['entryfee']+exitfee,slippage=slippage,funding=p['funding'],reason=reason,hold_hours=(ts-p['ts'])/3600))
        orders.append(dict(action='close',side=-side,symbol=s,ts=int(ts),information_ts=info,reason=reason,cash=cash))
        cool[s]=math.ceil((ts+21600)/3600)*3600
        if reason in ('gap_stop','stop_loss') and net<0:
            stops.append(ts)
            if sum(x>=ts-172800 for x in stops)>=2:guard=max(guard,math.ceil((ts+86400)/3600)*3600)
    def settle(s,i,ts,boundary=False):
        p=pos[s];rate=rates[s][i];signed=p['side']*rate
        if boundary and signed<=0:return
        payment=p['qty']*mk[s][i,0]*signed;p['funding']+=payment
        if payment:events.append(dict(symbol=s,ts=int(ts),direction=p['side'],rate=float(rate),payment=float(payment),new_boundary_entry=boundary))
    for i,t in enumerate(tslist):
        ts=int(t);endts=ts+300;info=ts-delay*60;dec=bool(z['decision'][i]);daily=dec and info%86400==0
        for s in pos:
            if not z['ok'][s][i] or not np.isfinite(mk[s][i]).all() or not np.isfinite(px[s][i]).all():issues.append(dict(ts=ts,symbol=s,kind='held_data_missing'))
        if issues:break
        for s in pos:settle(s,i,ts)
        for s,p in pos.items():
            mark=mk[s][i,0];coll=p['margin']+p['side']*p['qty']*(mark-p['fill'])-p['funding'];ratio=coll/(p['qty']*mark);minratio=min(minratio,ratio)
            if ratio<=.07:issues.append(dict(ts=ts,symbol=s,kind='collateral_stress_open',ratio=ratio))
        if issues:break
        for s in list(pos):
            p=pos[s];op,hi,lo,cp,vol=px[s][i]
            if vol>0 and p['side']*(op-p['stop'])<=0:close(s,op,ts,'gap_stop',info if dec else None)
        if dec:
            for s in list(pos):
                p=pos[s];direction=int(z['mom'][s][i]);sig=int(z['signals'][s][i]);reason=None
                if mode in ('long_control','momentum_ls') and daily and direction!=p['side']:reason='signal_exit'
                if mode.startswith('sweep'):
                    if sig and sig!=p['side']:reason='opposite_sweep'
                    if mode=='sweep_trend' and daily and direction!=p['side']:reason='trend_exit'
                    if ts-p['ts']>=86400:reason='time_exit'
                if reason and px[s][i,4]>0:close(s,px[s][i,0],ts,reason,info)
            for s in SYMBOLS:
                direction=int(z['mom'][s][i]) if mode in ('long_control','momentum_ls') and daily else int(z['signals'][s][i]) if mode.startswith('sweep') else 0
                if mode=='long_control' and direction<0:direction=0
                if mode=='sweep_trend' and direction!=z['mom'][s][i]:direction=0
                if s in pos or direction==0:continue
                if ts<cool.get(s,0) or ts<guard:blocked+=1;continue
                margin=float(z['budgets'][s][i]);notional=margin*leverage;entryfee=notional*fee
                if len(pos)>=2 or margin<10 or cash<margin+entryfee:continue
                if z['avail'][s][i]!=1 or not z['ok'][s][i] or not np.isfinite(mk[s][i]).all() or not np.isfinite(px[s][i]).all():issues.append(dict(ts=ts,symbol=s,kind='entry_data_missing'));continue
                if px[s][i,4]<=0:continue
                ref=float(px[s][i,0]);fill=ref*(1+direction*slip);qty=notional/fill;cash-=margin+entryfee
                pos[s]=dict(side=direction,margin=margin,qty=qty,fill=fill,ref=ref,entryfee=entryfee,funding=0.,ts=ts,stop=fill*(1-direction*.04))
                orders.append(dict(action='open',side=direction,symbol=s,ts=ts,information_ts=info,reason='entry',cash=cash));settle(s,i,ts,True)
        if issues:break
        worst=cash
        for s,p in pos.items():
            mark=mk[s][i,2 if p['side']==1 else 1];coll=p['margin']+p['side']*p['qty']*(mark-p['fill'])-p['funding'];worst+=coll
            ratio=coll/(p['qty']*mark);minratio=min(minratio,ratio)
            if ratio<=.07:issues.append(dict(ts=ts,symbol=s,kind='collateral_stress_intrabar',ratio=ratio))
        stressdd=max(stressdd,100*(1-worst/peak))
        if issues:break
        for s in list(pos):
            p=pos[s];adverse=px[s][i,2 if p['side']==1 else 1]
            if px[s][i,4]>0 and p['side']*(adverse-p['stop'])<=0:close(s,p['stop'],endts,'stop_loss',None)
        equity=cash+sum(p['margin']+p['side']*p['qty']*(mk[s][i,3]-p['fill'])-p['funding'] for s,p in pos.items())
        peak=max(peak,equity);dd=(1-equity/peak)*100;ddmax=max(ddmax,dd);mincash=min(mincash,cash)
        exposure=sum(p['qty']*mk[s][i,3] for s,p in pos.items())/equity if equity>0 else 0.;sumexp+=exposure;maxexp=max(maxexp,exposure)
        if endts%3600==0:curve.append([endts,equity,dd,exposure])
    if not issues:
        for s in list(pos):close(s,float(px[s][-1,3]),int(tslist[-1]+300),'window_end',None)
    valid=not issues and not pos;final=cash if valid else None;ledger=abs(1000+sum(x['pnl'] for x in trades)-cash) if valid else None
    if valid:
        assert ledger<1e-7 and mincash>=-1e-7
        ddmax=max(ddmax,(1-cash/peak)*100);curve[-1]=[int(tslist[-1]+300),cash,(1-cash/peak)*100,0.]
    days=(pd.Timestamp(end)-pd.Timestamp(start)).days+1
    return dict(mode=mode,name=NAMES[mode],venue='perp',leverage=leverage,start=start,end=end,fee=fee,slippage=slip,delay_minutes=delay,elapsed_days=days,initial=1000.,final_equity=final,return_pct=(cash/1000-1)*100 if valid else None,annualized_return_pct=((cash/1000)**(365/days)-1)*100 if valid and days>=365 and cash>0 else None,max_drawdown=ddmax if valid else None,observed_max_drawdown=ddmax,intrabar_simultaneous_low_stress_dd=stressdd,valid_for_comparison=valid,trade_count=len(trades),fees=sum(x['fees'] for x in trades),slippage_cost=sum(x['slippage'] for x in trades),funding_cost=sum(x['funding'] for x in trades),gross_pnl=sum(x['gross_pnl'] for x in trades),long_pnl=sum(x['pnl'] for x in trades if x['direction']=='long'),short_pnl=sum(x['pnl'] for x in trades if x['direction']=='short'),long_trades=sum(x['direction']=='long' for x in trades),short_trades=sum(x['direction']=='short' for x in trades),win_rate=100*sum(x['pnl']>0 for x in trades)/len(trades) if trades else None,minimum_collateral_ratio_pct=minratio*100 if minratio<1e8 else None,cash_min=mincash,ledger_error=ledger,mean_exposure_pct=100*sumexp/len(ix) if valid else None,max_exposure_pct=100*maxexp,blocked_entry_signals=blocked,data_issues=issues,trades=trades,orders=orders,funding_events=events,curve=base.compress_curve(curve),contributions={s:sum(x['pnl'] for x in trades if x['symbol']==s) for s in SYMBOLS})

def ident(start,end,mode,leverage,fee,delay):return f'{start}_{end}_{mode}_L{leverage}_f{round(fee*10000)}_d{delay}'
def cached_run(start,end,mode,leverage=1,fee=.001,delay=0):
    key=ident(start,end,mode,leverage,fee,delay);p=ROOT/'results'/(key+'.json.gz')
    if p.exists():return base.read(p)
    if mode=='long_control':
        r=old.cached_run(start,end,'btc_eth','perp',leverage,fee,delay).copy();r.update(mode=mode,name=NAMES[mode],long_pnl=sum(x['pnl'] for x in r['trades']),short_pnl=0.,long_trades=r['trade_count'],short_trades=0,win_rate=100*sum(x['pnl']>0 for x in r['trades'])/r['trade_count'] if r['trade_count'] else None)
        r['trades']=[dict(x,direction='long') for x in r['trades']]
    else:r=simulate(start,end,mode,leverage,fee,delay)
    r['id']=key;base.dump(p,r);return r
def summary(r):return {k:v for k,v in r.items() if k not in ('trades','orders','curve','selection_trace','funding_events','skipped_entries')}
