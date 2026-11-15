"""A fixed 1-second market-entry proxy preserving the original risk controls."""
import numpy as np
def near(a,b):return bool(np.isclose(float(a),float(b),rtol=1e-11,atol=1e-12))
def decide(e,old,tape):
    if old['status']!='verified':return {'status':'original_path_unverified'}
    t=tape.transact_time.to_numpy('int64');p=tape.price.to_numpy(float);side=int(e['side']);qend=int(e['quarter_end'])
    if not len(t) or np.any(t[1:]<t[:-1]) or not np.isfinite(p).all() or (p<=0).any():return {'status':'invalid_tape'}
    ref=int(np.searchsorted(t,int(e['entry_exec_ts']),side='left'))
    if ref>=len(t) or int(t[ref])!=int(e['entry_exec_ts']) or not near(p[ref],e['raw_entry_5s']):return {'status':'reference_disagreement'}
    oldidx=int(np.searchsorted(t,int(e['entry_exec_ts'])+5000,side='left'))
    if oldidx>=len(t) or int(t[oldidx])!=int(old['entry_ts']) or not near(p[oldidx],old['entry_raw']):return {'status':'baseline_entry_disagreement'}
    fill=int(np.searchsorted(t,int(e['entry_exec_ts'])+1000,side='left'))
    if fill>=len(t):return {'status':'missing_delayed_entry'}
    if int(t[fill])>=qend:return {'status':'entry_after_quarter_end'}
    lev=int(old['variant'].rsplit('_',1)[1].rstrip('x'));raw=float(p[fill]);entry=raw*(1+side*.0005)
    stop=float(old['initial_stop']);dist=side*(entry-stop);trigger=float(e['signal_close']);atr=float(e['atr'])
    bad=(dist<=0 or dist>1.5*atr or side*(entry-trigger)>.25*atr or dist/entry+.003>=.5*(1/lev-.01))
    if bad:signal=int(t[fill]);reason='filled_beyond_risk_budget'
    else:
        target=entry+side*2*dist;end=int(np.searchsorted(t,qend,side='right'));tt=t[fill:end];pp=p[fill:end]
        choices=[(qend,3,'quarter_time')];stops=np.flatnonzero(side*(pp-stop)<=0);targets=np.flatnonzero(side*(pp-target)>=0)
        if len(stops):choices.append((int(tt[stops[0]]),0,'stop'))
        if len(targets):choices.append((int(tt[targets[0]]),1,'target'))
        signal,_,reason=min(choices)
    out=int(np.searchsorted(t,signal+5000,side='left'))
    if out>=len(t):return {'status':'missing_delayed_exit'}
    return {'status':'verified','entry_ts':int(t[fill]),'entry_raw':raw,'entry_fill':entry,
            'entry_signal_reference_ts':int(e['entry_exec_ts']),'exit_signal_ts':signal,'exit_ts':int(t[out]),
            'exit_raw':float(p[out]),'exit_fill':float(p[out])*(1-side*.0005),'reason':reason,
            'initial_stop':stop,'target_r':2.,'fast_fail':False,'actual_entry_risk':dist}
