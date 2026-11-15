"""One-second flow confirmation and one-second market-entry proxy."""
import json,sys
from pathlib import Path
import numpy as np
H=Path(__file__).resolve().parent;ORIGINAL=H.parent/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(ORIGINAL))
from leveraged_paths import known_precheck
M=60000
def decide(e,tape,bars):
    minute=int(e['trigger_minute']);start=int(e['quarter_start']);qend=int(e['quarter_end'])
    if minute not in bars.index:return {'status':'missing_trigger_minute'}
    prior=bars.reindex(np.arange(start,minute,M,dtype=np.int64))
    if len(prior) and not np.isfinite(prior[['high','low']].to_numpy(float)).all():return {'status':'missing_quarter_prefix'}
    if len(prior) and ((prior.high>e['upper']).any() or (prior.low<e['lower']).any()):return {'status':'earlier_minute_cross_mismatch'}
    t=tape.transact_time.to_numpy(np.int64);p=tape.price.to_numpy(float)
    if not len(t) or np.any(t[1:]<t[:-1]) or not np.isfinite(p).all() or (p<=0).any():return {'status':'invalid_tape'}
    first=tape[(tape.transact_time>=minute)&(tape.transact_time<minute+M)]
    if first.empty:return {'status':'missing_trigger_ticks'}
    bar=bars.loc[minute];actual=[float(first.price.iloc[0]),float(first.price.max()),float(first.price.min()),float(first.price.iloc[-1])]
    official=[float(bar.open),float(bar.high),float(bar.low),float(bar.close)]
    if not np.allclose(actual,official,rtol=1e-9,atol=1e-12):return {'status':'minute_trade_ohlc_mismatch'}
    crosses=first[(first.price>e['upper'])|(first.price<e['lower'])]
    if crosses.empty:return {'status':'minute_without_public_cross'}
    c=crosses.iloc[0];decision=int(c.transact_time);side=1 if float(c.price)>e['upper'] else -1
    if not bool(e['long_known_eligible' if side==1 else 'short_known_eligible']):return {'status':'first_direction_ineligible','side':side}
    if decision+1000>=qend:return {'status':'no_order_time','side':side}
    ri=int(np.searchsorted(t,decision+1000,side='left'))
    if ri>=len(t):return {'status':'missing_one_second_reference','side':side}
    if int(t[ri])>=qend:return {'status':'no_order_time','side':side}
    w=tape[(tape.transact_time>decision)&(tape.transact_time<decision+1000)]
    maker=w.is_buyer_maker.astype(str).str.lower();v=w.price.to_numpy(float)*w.quantity.to_numpy(float)
    if len(w) and (not maker.isin(['true','false']).all() or not np.isfinite(v).all() or (v<=0).any()):return {'status':'invalid_flow_window'}
    buy=float(v[maker.eq('false').to_numpy()].sum());sell=float(v[maker.eq('true').to_numpy()].sum())
    imbalance=side*(buy-sell)/(buy+sell) if buy+sell>0 else None
    spec=json.loads(e['long_spec'] if side==1 else e['short_spec'])
    extra={'side':side,'decision_ts':decision,'signal_close':float(c.price),'entry_exec_ts':int(t[ri]),'raw_entry_1s':float(p[ri]),
           'one_count':len(w),'buy_notional':buy,'sell_notional':sell,'one_imbalance':imbalance,**spec}
    if len(w)<3 or imbalance is None or imbalance<.10 or side*(float(p[ri])-float(spec['level']))<=0:
        return {'status':'flow_filter_not_met',**extra}
    # The legacy precheck expects its reference under raw_entry_5s; this value is
    # the 1-second reference here. Its conservative 5s time buffer is retained.
    event={**e,**extra,'raw_entry_5s':float(p[ri])}
    prechecks={str(lev):known_precheck(event,lev) or 'passed' for lev in (10,20)};paths={}
    for lev in (10,20):
        if prechecks[str(lev)]=='passed':paths[f'one_observation_2r_{lev}x']=path(event,tape,lev)
    return {'status':'qualified' if paths else 'known_risk_rejected',**extra,'prechecks':prechecks,'paths':paths}
def path(e,tape,lev):
    t=tape.transact_time.to_numpy(np.int64);p=tape.price.to_numpy(float);side=int(e['side']);qend=int(e['quarter_end'])
    ref=int(np.searchsorted(t,int(e['entry_exec_ts']),side='left'))
    if ref>=len(t) or int(t[ref])!=int(e['entry_exec_ts']) or not np.isclose(p[ref],float(e['raw_entry_1s']),rtol=1e-11,atol=1e-12):return {'status':'reference_mismatch'}
    fill=int(np.searchsorted(t,int(t[ref])+1000,side='left'))
    if fill>=len(t):return {'status':'missing_delayed_entry'}
    entry_ts=int(t[fill]);raw=float(p[fill]);entry=raw*(1+side*.0005)
    if entry_ts>=qend:return {'status':'entry_after_quarter_end','entry_ts':entry_ts}
    stop=float(e['stop_price']);distance=side*(entry-stop);trigger=float(e['signal_close']);atr=float(e['atr'])
    invalid=(distance<=0 or distance>1.5*atr or side*(entry-trigger)>.25*atr or distance/entry+.003>=.5*(1/lev-.01))
    if invalid:signal=entry_ts;reason='filled_beyond_risk_budget'
    else:
        target=entry+side*2*distance;end=int(np.searchsorted(t,qend,side='right'));tt=t[fill:end];pp=p[fill:end]
        choices=[(qend,3,'quarter_time')];stops=np.flatnonzero(side*(pp-stop)<=0);targets=np.flatnonzero(side*(pp-target)>=0)
        if len(stops):choices.append((int(tt[stops[0]]),0,'stop'))
        if len(targets):choices.append((int(tt[targets[0]]),1,'target'))
        signal,_,reason=min(choices)
    out=int(np.searchsorted(t,signal+5000,side='left'))
    if out>=len(t):return {'status':'missing_delayed_exit','entry_ts':entry_ts,'exit_signal_ts':signal}
    exitraw=float(p[out]);return {'status':'verified','entry_ts':entry_ts,'entry_raw':raw,'entry_fill':entry,
        'entry_signal_reference_ts':int(t[ref]),'exit_signal_ts':signal,'exit_ts':int(t[out]),'exit_raw':exitraw,
        'exit_fill':exitraw*(1-side*.0005),'reason':reason,'initial_stop':stop,'target_r':2.,'fast_fail':False,'actual_entry_risk':distance}
