"""Frozen four-variant spot/perpetual execution; no account access."""
from pathlib import Path
from functools import lru_cache
import sys,hashlib,math
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent;RESEARCH=ROOT.parent
sys.path.insert(0,str(RESEARCH/'pool-optimization-v1'));import pool_engine as prior
base=prior.old.base
NAMES={'slow_base':'较慢选币基准','rank_buffer':'排名缓冲 · 前二进前四留','delayed_retry':'止损后延迟至下周','btc_eth':'BTC/ETH · 相同波动预算'}
SCENARIOS=[('main','2025-01-01','2026-10-31',.001,0),('2025','2025-01-01','2025-12-31',.001,0),('2026','2026-01-01','2026-10-31',.001,0),('double','2025-01-01','2026-10-31',.002,0),('triple','2025-01-01','2026-10-31',.003,0),('delay','2025-01-01','2026-10-31',.001,5)]

@lru_cache(maxsize=1)
def manifest():return base.read(ROOT/'data-manifest.json')

@lru_cache(maxsize=256)
def load_frame(venue,s,kind):
    file=f'data/{venue}/{s}-{kind}.parquet';entry=manifest()['processed'].get(file) or manifest()['processed'].get(str(Path(file)))
    if entry:
        path=ROOT/file;assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
        return pd.read_parquet(path)
    if venue=='spot':return prior.execution_data(s,kind)
    return None

def retained_selection(ranked,held):
    symbols=[x['symbol'] for x in ranked]
    chosen=[s for s in symbols[:4] if s in held]
    for s in symbols[:2]:
        if s not in chosen and len(chosen)<2:chosen.append(s)
    return chosen

@lru_cache(maxsize=12)
def prepared(start,end,venue,tf):
    trace=[r for r in prior.slow_rankings() if start<=r['date']<=end]
    symbols=tuple(sorted({'BTCUSDT','ETHUSDT'}|{x['symbol'] for r in trace for x in r['ranked'][:4]}))
    step=3600 if tf=='1h' else 300
    index=pd.date_range(pd.Timestamp(start,tz='UTC'),pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1),freq=f'{step}s',inclusive='left')
    prices={};marks={};rates={};funding_ok={};available={};mapping=manifest()['mapping']
    for s in symbols:
        c=mapping.get(s) if venue=='perp' else s
        d=load_frame(venue,c,'klines' if venue=='perp' else tf) if c else None
        mark=load_frame('perp',c,'markPriceKlines') if venue=='perp' and c else None
        if d is None:
            prices[s]=np.full((len(index),4),np.nan);available[s]=np.zeros(len(index),dtype=bool)
        else:
            prices[s]=d.reindex(index)[['open','low','close','volume']].to_numpy(dtype=float)
            prev=d.reindex(index-pd.Timedelta(seconds=step))
            available[s]=(prev.volume.gt(0)&prev.close.gt(0)).to_numpy()
        if venue=='perp':
            marks[s]=mark.reindex(index)[['open','low','close']].to_numpy(dtype=float) if mark is not None else np.full((len(index),3),np.nan)
            prevmark=mark.reindex(index-pd.Timedelta(seconds=step)).close.gt(0).to_numpy() if mark is not None else np.zeros(len(index),dtype=bool)
            # Existing execution history plus missing mark is a data gap, not evidence of no contract.
            available[s]=np.where(available[s],np.where(prevmark,1,2),0)
            fd=load_frame('perp',c,'fundingRate') if c else None
            rates[s]=fd.last_funding_rate.reindex(index).fillna(0).to_numpy() if fd is not None else np.zeros(len(index))
            valid=np.zeros(len(index),dtype=bool)
            if fd is not None:
                # Coverage is an ex-post integrity check only, never used to select entries.
                for when,row in fd.iterrows():
                    lo=index.searchsorted(when-pd.Timedelta(hours=float(row.funding_interval_hours)))
                    hi=index.searchsorted(when,side='right');valid[lo:hi]=True
                if len(fd):
                    last=fd.index[-1];hi=index.searchsorted(last+pd.Timedelta(hours=float(fd.funding_interval_hours.iloc[-1])))
                    valid[index.searchsorted(last):hi]=True
                valid&=np.array([d.strftime('%Y-%m') in manifest()['availability'].get(s,{}).get('fundingRate',[]) for d in index])
            funding_ok[s]=valid
    known={};factors=prior.old.rankings()[0]
    for r in trace:
        day=pd.Timestamp(r['date'],tz='UTC');src=day-pd.Timedelta(days=1)
        known[int(day.timestamp())]={s:(bool(factors[s].loc[src,'valid'] and factors[s].loc[src,'mom']>0),float(min(200,2/factors[s].loc[src,'sigma'])) if np.isfinite(factors[s].loc[src,'sigma']) and factors[s].loc[src,'sigma']>0 else 0.) for s in symbols}
    return symbols,index,prices,marks,rates,funding_ok,available,{int(pd.Timestamp(r['date'],tz='UTC').timestamp()):r for r in trace},known

def simulate(start,end,mode,venue='spot',leverage=1,fee=.001,delay=0,tf='5m',full_curve=False,fixture=None):
    assert mode in NAMES and venue in ('spot','perp') and leverage in range(1,11)
    assert tf in ('1h','5m') and (not delay or tf=='5m') and (venue=='spot' and leverage==1 or venue=='perp' and tf=='5m')
    symbols,index,prices,marks,rates,funding_ok,available,trace,known=fixture if fixture is not None else prepared(start,end,venue,tf)
    if mode=='btc_eth':symbols=('BTCUSDT','ETHUSDT')
    step=3600 if tf=='1h' else 300;times=index.as_unit('s').asi8;slip=.0005
    cash=1000.;pos={};last={};cooldown={};stoptimes=[];guard=0;guards=0;blocked=0;peak=1000.;maxdd=0.;mincash=1000.;totalexp=0.;maxexp=0.;minratio=1e9;stressdd=0.
    chosen=[];selection=[];orders=[];trades=[];fund_events=[];skips=[];issues=[];curve=[[int(times[0]),1000.,0.,0.]]
    last_eq=1000.;halted=False
    def close(s,ref,ts,reason,info):
        nonlocal cash,guard,guards
        p=pos.pop(s);fill=ref*(1-slip);exitfee=p['qty']*fill*fee
        pricepnl=p['qty']*(fill-p['fill']);net=pricepnl-p['entryfee']-exitfee-p['funding']
        if venue=='spot':cash+=p['qty']*fill-exitfee
        else:cash+=p['margin']+pricepnl-exitfee-p['funding']
        slipcost=p['qty']*(p['fill']-p['ref']+ref-fill)
        trades.append({'symbol':s,'contract':manifest()['mapping'].get(s) if venue=='perp' and fixture is None else s,'entry_ts':p['ts'],'exit_ts':int(ts),'entry_price':p['fill'],'exit_price':fill,'entry_reference':p['ref'],'exit_reference':ref,'qty':p['qty'],'stake':p['margin'],'margin':p['margin'],'notional':p['margin']*leverage,'pnl':net,'gross_pnl':net+p['entryfee']+exitfee+slipcost+p['funding'],'fees':p['entryfee']+exitfee,'slippage':slipcost,'funding':p['funding'],'hold_hours':(ts-p['ts'])/3600,'reason':reason,'stop_distance':.04})
        orders.append({'side':'sell','symbol':s,'ts':int(ts),'information_ts':info,'price':fill,'qty':p['qty'],'cash':cash,'reason':reason})
        cooldown[s]=math.ceil((ts+21600)/3600)*3600
        if reason in ('gap_stop','stop_loss') and net<0:
            stoptimes.append(ts)
            if mode=='delayed_retry':
                mid=pd.Timestamp(ts,unit='s',tz='UTC').normalize();nxt=int((mid+pd.Timedelta(days=7-mid.weekday())).timestamp());cooldown[s]=max(cooldown[s],nxt)
            if sum(t>=ts-172800 for t in stoptimes)>=2:guard=max(guard,math.ceil((ts+86400)/3600)*3600);guards+=1
    def settle(s,i,ts,boundary=False):
        rate=rates[s][i]
        if boundary and rate<=0:return
        amount=pos[s]['qty']*marks[s][i,0]*rate
        pos[s]['funding']+=amount
        if amount:fund_events.append({'symbol':s,'ts':int(ts),'rate':float(rate),'payment':float(amount),'new_boundary_entry':boundary})
    for i,rawts in enumerate(times):
        ts=int(rawts);endts=ts+step;info=ts-delay*60;daily=info in trace
        if daily:
            row=trace[info]
            if not selection or pd.Timestamp(row['date']).weekday()==0:
                chosen=list(symbols) if mode=='btc_eth' else retained_selection(row['ranked'],pos) if mode=='rank_buffer' else list(row['daily_top2'])
            selection.append({**row,'selected':list(chosen),'held_before_decision':list(pos)})
        if venue=='perp':
            for s in pos:
                if not funding_ok[s][i] or not np.isfinite(marks[s][i]).all():issues.append({'ts':ts,'symbol':s,'kind':'held_mark_or_funding_coverage_missing'})
            if issues:halted=True;break
            for s in list(pos):settle(s,i,ts)
            # At the open, mark collateral checks precede ordinary gap/strategy exits.
            for s,p in pos.items():
                ratio=(p['margin']+p['qty']*(marks[s][i,0]-p['fill'])-p['funding'])/(p['qty']*marks[s][i,0]);minratio=min(minratio,ratio)
                if ratio<=.07:issues.append({'ts':ts,'symbol':s,'kind':'collateral_stress_open','ratio':ratio})
            if issues:halted=True;break
        for s in list(pos):
            op,low,cp,vol=prices[s][i]
            if not np.isfinite(op):issues.append({'ts':ts,'symbol':s,'kind':'held_execution_price_missing'});continue
            if vol>0 and op<=pos[s]['stop']:close(s,op,ts,'gap_stop',info if (info%3600==0) else None)
        if issues:halted=True;break
        if daily:
            for s in list(pos):
                positive,amount=known[info][s];op,low,cp,vol=prices[s][i]
                if np.isfinite(op) and vol>0 and (not positive or s not in chosen):close(s,op,ts,'signal_exit',info)
            for s in symbols:
                positive,margin=known[info][s];op,low,cp,vol=prices[s][i]
                if s in pos or not positive or s not in chosen:continue
                if venue=='perp' and available[s][i]==2:issues.append({'ts':ts,'symbol':s,'kind':'previous_mark_data_missing'});continue
                if venue=='perp' and not available[s][i]:skips.append({'ts':ts,'symbol':s,'kind':'no_previous_executable_contract_bar'});continue
                if not (np.isfinite(op) and vol>0):skips.append({'ts':ts,'symbol':s,'kind':'no_entry_price'});continue
                if ts<cooldown.get(s,0) or ts<guard:blocked+=1;continue
                notional=margin*leverage;entryfee=notional*fee
                if margin<10 or len(pos)>=2:continue
                if cash<margin+entryfee:skips.append({'ts':ts,'symbol':s,'kind':'insufficient_cash'});continue
                fill=float(op)*(1+slip);qty=notional/fill;cash-=margin+entryfee
                pos[s]={'margin':margin,'qty':qty,'fill':fill,'ref':float(op),'entryfee':entryfee,'funding':0.,'ts':ts,'stop':fill*.96}
                orders.append({'side':'buy','symbol':s,'ts':ts,'information_ts':info,'price':fill,'qty':qty,'cash':cash,'reason':'entry'})
                if venue=='perp':
                    if not funding_ok[s][i] or not np.isfinite(marks[s][i]).all():issues.append({'ts':ts,'symbol':s,'kind':'entry_mark_or_funding_missing'})
                    else:settle(s,i,ts,True)
        if issues:halted=True;break
        if venue=='perp':
            low_equity=cash
            for s,p in pos.items():
                low=marks[s][i,1];coll=p['margin']+p['qty']*(low-p['fill'])-p['funding'];ratio=coll/(p['qty']*low);minratio=min(minratio,ratio);low_equity+=coll
                if ratio<=.07:issues.append({'ts':ts,'symbol':s,'kind':'collateral_stress_intrabar','ratio':ratio})
            stressdd=max(stressdd,100*(1-low_equity/peak))
            if issues:halted=True;break
        for s in list(pos):
            op,low,cp,vol=prices[s][i]
            if np.isfinite(low) and vol>0 and low<=pos[s]['stop']:close(s,pos[s]['stop'],endts,'stop_loss',None)
        for s in pos:
            cp=prices[s][i,2] if venue=='spot' else marks[s][i,2]
            if np.isfinite(cp):last[s]=float(cp)
        value=sum(p['qty']*last[s] for s,p in pos.items())
        equity=cash+value if venue=='spot' else cash+sum(p['margin']+p['qty']*(last[s]-p['fill'])-p['funding'] for s,p in pos.items())
        peak=max(peak,equity);dd=(1-equity/peak)*100;maxdd=max(maxdd,dd);exp=value/equity if equity>0 else 0
        totalexp+=exp;maxexp=max(maxexp,exp);mincash=min(mincash,cash);last_eq=equity
        if full_curve or endts%3600==0:curve.append([endts,equity,dd,exp])
    if not halted:
        for s in list(pos):
            cp=prices[s][-1,2];vol=prices[s][-1,3]
            if np.isfinite(cp) and vol>0:close(s,float(cp),int(times[-1]+step),'window_end',None)
            else:issues.append({'ts':int(times[-1]),'symbol':s,'kind':'cannot_close_window'})
    valid=not issues and not pos;final=cash if valid else None
    error=abs(1000+sum(t['pnl'] for t in trades)-cash) if valid else None
    if valid:
        assert error<1e-7 and mincash>=-1e-7
        maxdd=max(maxdd,(1-cash/peak)*100);curve[-1]=[int(times[-1]+step),cash,(1-cash/peak)*100,0.]
    wins=[t['pnl'] for t in trades if t['pnl']>0]
    days=(pd.Timestamp(end)-pd.Timestamp(start)).days+1
    result={'mode':mode,'name':NAMES[mode],'venue':venue,'leverage':leverage,'start':start,'end':end,'fee':fee,'slippage':slip,'resolution':tf,'delay_minutes':delay,'initial':1000.,'final_equity':final,'return_pct':(final/1000-1)*100 if valid else None,'annualized_return_pct':((final/1000)**(365/days)-1)*100 if valid and days>=365 else None,'elapsed_days':days,'max_drawdown':maxdd if valid else None,'observed_max_drawdown':maxdd,'intrabar_simultaneous_low_stress_dd':stressdd if venue=='perp' else None,'trade_count':len(trades),'mean_exposure_pct':totalexp/len(index)*100 if valid else None,'max_exposure_pct':maxexp*100,'minimum_collateral_ratio_pct':minratio*100 if minratio<1e8 else None,'fees':sum(t['fees'] for t in trades),'slippage_cost':sum(t['slippage'] for t in trades),'funding_cost':sum(t['funding'] for t in trades),'gross_pnl':sum(t['gross_pnl'] for t in trades),'turnover':sum(t['qty']*(t['entry_price']+t['exit_price']) for t in trades)/1000,'cash_min':mincash,'ledger_error':error,'guard_activations':guards,'blocked_entry_signals':blocked,'valid_for_comparison':valid,'data_issues':issues,'skipped_entries':skips,'skip_count':len(skips),'halted':halted,'open_positions':len(pos),'partial_equity_before_halt':last_eq if halted else None,'top3_profit_share':sum(sorted(wins,reverse=True)[:3])/sum(wins)*100 if wins else None,'contributions':{s:sum(t['pnl'] for t in trades if t['symbol']==s) for s in symbols},'trades':trades,'orders':orders,'funding_events':fund_events,'selection_trace':selection,'curve':curve if full_curve else base.compress_curve(curve),'drawdown_basis':'all execution closes; mark closes for perpetual; invalid paths suppressed; intrabar minima stress reported separately'}
    return result

def key(start,end,mode,venue,leverage,fee,delay,tf):return f'{start}_{end}_{mode}_{venue}_L{leverage}_f{round(fee*10000)}_d{delay}_{tf}'+('_V2' if venue=='perp' else '')
def cached_run(start,end,mode,venue='spot',leverage=1,fee=.001,delay=0,tf='5m'):
    ident=key(start,end,mode,venue,leverage,fee,delay,tf);path=ROOT/'results'/(ident+'.json.gz')
    if path.exists():return base.read(path)
    r=simulate(start,end,mode,venue,leverage,fee,delay,tf);r['id']=ident;base.dump(path,r);return r
def summary(r):return {k:v for k,v in r.items() if k not in ('trades','orders','curve','selection_trace','funding_events','skipped_entries')}
