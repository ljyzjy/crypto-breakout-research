"""Deterministic spot research engine; no exchange client, credentials, or paper DB."""
from pathlib import Path
from functools import lru_cache
import gzip, hashlib, json, math, zipfile
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
KIT=ROOT.parent
SYMBOLS=('BTCUSDT','ETHUSDT')
MODES=('DailyMomentum','breakout','pullback','reversion','breakout_volume','breakout_flow')
NAMES={'DailyMomentum':'30 日动量 · 同口径对照','breakout':'A · 小时突破','pullback':'B · 趋势回撤',
       'reversion':'C · 震荡反转','breakout_volume':'A + 成交额确认','breakout_flow':'A + 主动买盘确认'}
HOLD={'DailyMomentum':None,'breakout':48,'pullback':24,'reversion':6,'breakout_volume':48,'breakout_flow':48}
HOUR=3600


def dump(path,data):
    path=Path(path);path.parent.mkdir(exist_ok=True,parents=True)
    value=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    tmp=path.with_suffix(path.suffix+'.tmp')
    if path.suffix=='.gz':
        with gzip.open(tmp,'wt',encoding='utf-8') as f:f.write(value)
    else:tmp.write_text(value,encoding='utf-8')
    tmp.replace(path)


def read(path):
    path=Path(path)
    if path.suffix=='.gz':
        with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)
    return json.loads(path.read_text(encoding='utf-8'))


def load_raw():
    """Derived copies stay here; every archive must match the previously audited hash."""
    audit=read(ROOT/'数据可用性审计.json');parts={}
    for item in audit['archives']:
        path=KIT/'user_data/data/archive'/item['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Archive changed: '+path.name)
        with zipfile.ZipFile(path) as z:
            with z.open(z.namelist()[0]) as f:d=pd.read_csv(f,header=None)
        unit='us' if d[0].iloc[0]>=10**14 else 'ms'
        d=d.rename(columns={1:'open',2:'high',3:'low',4:'close',5:'volume',7:'quote_volume',8:'trades',10:'buy_quote'})
        d['date']=pd.to_datetime(d[0],unit=unit,utc=True)
        symbol,tf,*_=path.stem.split('-')
        parts.setdefault((symbol,tf),[]).append(d[['date','open','high','low','close','volume','quote_volume','trades','buy_quote']])
    out={}
    for key,chunks in parts.items():
        d=pd.concat(chunks).sort_values('date').set_index('date')
        assert not d.index.duplicated().any()
        out[key]=d
    return out


def features(raw):
    index=pd.date_range(raw.index.min(),raw.index.max(),freq='h')
    d=raw.reindex(index);valid=d[['open','high','low','close','volume','quote_volume','buy_quote']].notna().all(axis=1)&d.volume.gt(0)&d.quote_volume.gt(0)
    x=d.where(valid);c=x.close
    f=pd.DataFrame(index=index)
    tr=pd.concat([x.high-x.low,(x.high-c.shift()).abs(),(x.low-c.shift()).abs()],axis=1).max(axis=1).where(valid & valid.shift(1,fill_value=False))
    atr=tr.rolling(14,min_periods=14).mean().replace(0,np.nan)
    complete25=valid.rolling(25).sum().eq(25)
    f['M24']=(c/c.shift(24)-1).where(complete25)
    upper=x.high.shift().rolling(24).max();lower=x.low.shift().rolling(6).min()
    f['BR24']=(c-upper)/atr
    f['RVOL']=x.quote_volume/x.quote_volume.shift().rolling(168).median().replace(0,np.nan)
    f['TBI4']=2*x.buy_quote.rolling(4).sum()/x.quote_volume.rolling(4).sum().replace(0,np.nan)-1
    vwap=x.quote_volume.rolling(24).sum()/x.volume.rolling(24).sum().replace(0,np.nan)
    f['D24']=(c-vwap)/atr;f['NATR14']=atr/c
    f['ER24']=(c-c.shift(24)).abs()/c.diff().abs().rolling(24).sum().replace(0,np.nan)
    fast=c.ewm(span=24,adjust=False).mean();slow=c.ewm(span=72,adjust=False).mean()
    warm=valid.rolling(720).sum().eq(720)
    buys={'breakout':c>upper,'pullback':warm&(fast>slow)&(c.shift()<=vwap.shift())&(c>vwap),
          'reversion':(f.ER24<=.25)&(f.D24.shift() < -2)&(f.D24>=-1)}
    sells={'breakout':c<lower,'pullback':warm&((fast<=slow)|(c>=upper)),'reversion':c>=vwap}
    buys['breakout_volume']=buys['breakout']&(f.RVOL>=1.5);buys['breakout_flow']=buys['breakout']&(f.TBI4>0)
    sells['breakout_volume']=sells['breakout'];sells['breakout_flow']=sells['breakout']
    # Match the original DailyCandidates daily signal, including missing-day exclusion.
    daily=d.close.resample('1D',closed='left',label='right').last()
    daily=daily[d.close.resample('1D',closed='left',label='right').count().eq(24)]
    mom=daily/daily.shift(30)-1
    # Existing merge_asof carries the last complete day's information through an incomplete day.
    available=pd.Series(mom.to_numpy(),index=mom.index-pd.Timedelta(hours=1)).reindex(index).ffill()
    buys['DailyMomentum']=(available>0)&(d.volume>0)&(index.hour==23)
    sells['DailyMomentum']=(available<=0)&(d.volume>0)&(index.hour==23)
    for mode in MODES:
        f[mode+'_buy']=buys[mode].fillna(False)
        f[mode+'_sell']=sells[mode].fillna(False)
    f['ema24']=fast;f['ema72']=slow;f['vwap24']=vwap;f['atr14']=atr
    return f


@lru_cache(maxsize=1)
def inputs():
    raw=load_raw()
    return raw,{s:features(raw[(s,'1h')]) for s in SYMBOLS}


def compress_curve(rows,limit=1400):
    if len(rows)<=limit:return rows
    stride=math.ceil(len(rows)/(limit/5));out=[]
    for k in range(0,len(rows),stride):
        a=rows[k:k+stride]
        out.extend(sorted({tuple(a[0]),tuple(a[-1]),tuple(min(a,key=lambda r:r[1])),tuple(max(a,key=lambda r:r[1])),tuple(max(a,key=lambda r:r[2]))}))
    return [list(r) for r in out]


def simulate(start,end,mode,fee=.001,resolution='1h',delay=0,data=None,signal_frames=None,full_curve=False):
    if mode not in MODES or resolution not in ('1h','5m') or delay not in (0,5):raise ValueError('Unsupported fixed scenario')
    if delay and resolution!='5m':raise ValueError('Delay requires five-minute bars')
    if data is None:data,signal_frames=inputs()
    if signal_frames is None:signal_frames={s:features(data[(s,'1h')]) for s in SYMBOLS}
    begin=pd.Timestamp(start,tz='UTC');finish=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)
    step=3600 if resolution=='1h' else 300
    index=pd.date_range(begin,finish-pd.Timedelta(seconds=step),freq=f'{step}s')
    times=index.as_unit('s').asi8;frame={s:data[(s,resolution)].reindex(index) for s in SYMBOLS}
    prices={s:frame[s][['open','low','close','volume']].to_numpy() for s in SYMBOLS}
    # decision_t is strictly after the source hour's close; never merge future hours backward.
    decision_times=index-pd.Timedelta(minutes=delay)
    decision=(decision_times.minute==0)&(decision_times.second==0)
    src=decision_times-pd.Timedelta(hours=1)
    signals={s:signal_frames[s].reindex(src)[[mode+'_buy',mode+'_sell']].fillna(False).to_numpy(dtype=bool) for s in SYMBOLS}
    cash=1000.;positions={};last={};cooldown={};guard_until=0;stops=[];trades=[];orders=[];curve=[];gaps=[]
    peak=1000.;maxdd=0.;exposure_sum=0.;cash_min=1000.;guards=0;blocked=0;slip=.0005
    curve.append([int(times[0]),1000.,0.,0.])

    def close(s,ref,ts,reason,information_time):
        nonlocal cash,guard_until,guards
        p=positions.pop(s);fill=ref*(1-slip);exitfee=p['qty']*fill*fee
        proceeds=p['qty']*fill-exitfee;cash+=proceeds;pnl=proceeds-p['cost']
        slip_cost=p['qty']*(p['fill']-p['ref']+ref-fill)
        fees=p['entry_fee']+exitfee
        t={'symbol':s,'entry_ts':p['ts'],'exit_ts':int(ts),'entry_price':p['fill'],'exit_price':fill,
           'entry_reference':p['ref'],'exit_reference':ref,'qty':p['qty'],'stake':100.,'pnl':pnl,
           'return_pct':pnl/p['cost']*100,'fees':fees,'slippage':slip_cost,'gross_pnl':pnl+fees+slip_cost,
           'hold_hours':(ts-p['ts'])/3600,'reason':reason}
        trades.append(t);orders.append({'side':'sell','symbol':s,'ts':int(ts),'information_ts':information_time,'price':fill,'qty':p['qty'],'cash':cash,'reason':reason})
        cooldown[s]=math.ceil((ts+6*3600)/3600)*3600
        if reason in ('gap_stop','stop_loss') and pnl<0:
            stops.append(ts)
            if sum(t0>=ts-48*3600 for t0 in stops)>=2:
                guard_until=max(guard_until,math.ceil((ts+24*3600)/3600)*3600);guards+=1

    for i,ts in enumerate(times):
        ts=int(ts);endts=ts+step;is_decision=bool(decision[i]);info=int(ts-delay*60) if is_decision else None
        for s in list(positions):
            op,low,cp,vol=prices[s][i]
            if not np.isfinite(op):
                gaps.append({'ts':ts,'symbol':s,'kind':'held_missing_price'});continue
            if vol>0 and op<=positions[s]['stop']:close(s,op,ts,'gap_stop',info)
        if is_decision:
            for s in list(positions):
                op,low,cp,vol=prices[s][i];p=positions[s]
                if not (np.isfinite(op) and vol>0):continue
                due=HOLD[mode] is not None and info-p['ts']>=HOLD[mode]*3600
                if signals[s][i,1] or due:close(s,op,ts,'signal_exit' if signals[s][i,1] else 'time_exit',info)
            for s in SYMBOLS:
                op,low,cp,vol=prices[s][i];buy,sell=signals[s][i]
                if s in positions or not buy or sell or not (np.isfinite(op) and vol>0):continue
                if ts<cooldown.get(s,0) or ts<guard_until:blocked+=1;continue
                if len(positions)>=2 or cash<100*(1+fee):continue
                fill=float(op)*(1+slip);qty=100/fill;entryfee=100*fee;cost=100+entryfee;cash-=cost
                positions[s]={'ref':float(op),'fill':fill,'qty':qty,'cost':cost,'entry_fee':entryfee,'stop':fill*.96,'ts':ts}
                orders.append({'side':'buy','symbol':s,'ts':ts,'information_ts':info,'price':fill,'qty':qty,'cash':cash,'reason':'entry'})
        # Only now is the execution bar's low observed. No symbol can use that future low to block an earlier entry.
        for s in list(positions):
            op,low,cp,vol=prices[s][i]
            if np.isfinite(low) and vol>0 and low<=positions[s]['stop']:close(s,positions[s]['stop'],endts,'stop_loss',None)
        for s in SYMBOLS:
            cp=prices[s][i,2]
            if np.isfinite(cp):last[s]=float(cp)
        value=sum(p['qty']*last[s] for s,p in positions.items());equity=cash+value
        peak=max(peak,equity);dd=(1-equity/peak)*100;maxdd=max(maxdd,dd);exposure=value/equity
        exposure_sum+=exposure;cash_min=min(cash_min,cash)
        if full_curve or step==3600 or endts%3600==0:curve.append([endts,equity,dd,exposure])
    for s in list(positions):
        cp=prices[s][-1,2];vol=prices[s][-1,3]
        if np.isfinite(cp) and vol>0:close(s,float(cp),int(times[-1]+step),'window_end',None)
        else:gaps.append({'ts':int(times[-1]),'symbol':s,'kind':'cannot_close_at_window_end'})
    final=cash+sum(p['qty']*last[s] for s,p in positions.items());maxdd=max(maxdd,(1-final/peak)*100)
    curve[-1]=[int(times[-1]+step),final,(1-final/peak)*100,0. if not positions else curve[-1][3]]
    pnls=[t['pnl'] for t in trades];wins=[x for x in pnls if x>0];losses=[x for x in pnls if x<0]
    reconcile=abs(1000+sum(pnls)-final) if not positions else None
    if cash_min < -1e-7 or (reconcile is not None and reconcile>1e-7):raise AssertionError('Ledger/cash constraint failed')
    return {'mode':mode,'name':NAMES[mode],'start':start,'end':end,'fee':fee,'slippage':slip,'resolution':resolution,'delay_minutes':delay,
            'initial':1000,'final_equity':final,'return_pct':(final/1000-1)*100,'max_drawdown':maxdd,'trade_count':len(trades),
            'win_rate':len(wins)/len(trades)*100 if trades else 0.,'profit_factor':sum(wins)/-sum(losses) if losses else None,
            'mean_trade_pnl':float(np.mean(pnls)) if pnls else 0.,'median_trade_pnl':float(np.median(pnls)) if pnls else 0.,
            'mean_hold_hours':float(np.mean([t['hold_hours'] for t in trades])) if trades else 0.,
            'mean_exposure_pct':exposure_sum/len(times)*100,'fees':sum(t['fees'] for t in trades),'slippage_cost':sum(t['slippage'] for t in trades),
            'gross_pnl':sum(t['gross_pnl'] for t in trades),'turnover':sum(t['qty']*(t['entry_price']+t['exit_price']) for t in trades)/1000,
            'top3_profit_share':sum(sorted(wins,reverse=True)[:3])/sum(wins)*100 if wins else None,
            'contributions':{s:sum(t['pnl'] for t in trades if t['symbol']==s) for s in SYMBOLS},
            'guard_activations':guards,'blocked_entry_signals':blocked,'data_issues':gaps,'valid_for_comparison':not gaps,
            'cash_min':cash_min,'ledger_error':reconcile,'open_positions':len(positions),
            'trades':trades,'orders':orders,'curve':curve if full_curve else compress_curve(curve),
            'max_drawdown_basis':'all execution-bar closing valuations; chart sampled to hours then compressed; not intrabar worst loss'}


def scenario_id(start,end,mode,fee,resolution,delay=0):
    return f'{start}_{end}_{mode}_{int(round(fee*10000))}_{resolution}_d{delay}'


def cached_run(start,end,mode,fee=.001,resolution='1h',delay=0):
    key=scenario_id(start,end,mode,fee,resolution,delay);path=ROOT/'results'/(key+'.json.gz')
    if path.exists():return read(path)
    result=simulate(start,end,mode,fee,resolution,delay);result['id']=key;dump(path,result);return result
