"""Replay a 1R exit from the identical verified 2R entry and source tape."""
import numpy as np
def close(a,b):return bool(np.isclose(float(a),float(b),rtol=1e-11,atol=1e-12))
def decide(e,old,tape):
    if old['status']!='verified':return {'status':'original_path_unverified'}
    t=tape.transact_time.to_numpy('int64');p=tape.price.to_numpy(float);side=int(e['side']);qend=int(e['quarter_end'])
    if not len(t) or np.any(t[1:]<t[:-1]) or not np.isfinite(p).all() or (p<=0).any():return {'status':'invalid_tape'}
    ref=int(np.searchsorted(t,int(e['entry_exec_ts']),side='left'))
    if ref>=len(t) or int(t[ref])!=int(e['entry_exec_ts']) or not close(p[ref],e['raw_entry_5s']):return {'status':'reference_disagreement'}
    entryidx=int(np.searchsorted(t,int(e['entry_exec_ts'])+5000,side='left'))
    if entryidx>=len(t) or int(t[entryidx])!=int(old['entry_ts']) or not close(p[entryidx],old['entry_raw']):return {'status':'entry_disagreement'}
    entry=float(p[entryidx])*(1+side*.0005);stop=float(old['initial_stop']);dist=side*(entry-stop)
    if not close(entry,old['entry_fill']):return {'status':'entry_slippage_disagreement'}
    oldidx=int(np.searchsorted(t,int(old['exit_signal_ts'])+5000,side='left'))
    if oldidx>=len(t) or int(t[oldidx])!=int(old['exit_ts']) or not close(p[oldidx],old['exit_raw']):return {'status':'old_exit_disagreement'}
    if old['reason']=='filled_beyond_risk_budget':signal=int(old['entry_ts']);reason='filled_beyond_risk_budget'
    else:
        if dist<=0:return {'status':'nonpositive_risk'}
        target=entry+side*dist;end=int(np.searchsorted(t,qend,side='right'));tt=t[entryidx:end];pp=p[entryidx:end]
        choices=[(qend,2,'quarter_time')];stops=np.flatnonzero(side*(pp-stop)<=0);targets=np.flatnonzero(side*(pp-target)>=0)
        if len(stops):choices.append((int(tt[stops[0]]),0,'stop'))
        if len(targets):choices.append((int(tt[targets[0]]),1,'target'))
        signal,_,reason=min(choices)
    if signal>int(old['exit_signal_ts']):return {'status':'exit_order_disagreement'}
    idx=int(np.searchsorted(t,signal+5000,side='left'))
    if idx>=len(t):return {'status':'missing_delayed_exit'}
    raw=float(p[idx]);return {'status':'verified','entry_ts':int(t[entryidx]),'entry_raw':float(p[entryidx]),'entry_fill':entry,
       'entry_signal_reference_ts':int(e['entry_exec_ts']),'exit_signal_ts':signal,'exit_ts':int(t[idx]),'exit_raw':raw,
       'exit_fill':raw*(1-side*.0005),'reason':reason,'initial_stop':stop,'target_r':1.,'fast_fail':False,'actual_entry_risk':dist}
