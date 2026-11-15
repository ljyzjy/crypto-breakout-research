"""P10 pullback is observed; the hypothetical market order fills at P15 or later."""
import sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent/'第三十三轮_动态池逐笔执行'))
from leveraged_paths import known_precheck,M
SLIP=.0005;DELAY=5_000;FAIL=2_000

def simulate_pullback(e,ticks,leverage,fast_fail):
    side=int(e['side']);ts=ticks.transact_time.to_numpy(np.int64);price=ticks.price.to_numpy(float)
    if not len(ts) or not np.isfinite(price).all() or (price<=0).any() or np.any(ts[1:]<ts[:-1]):return {'status':'bad_tape'}
    minute=int(e['trigger_minute']);end=int(e['quarter_end']);up=float(e['upper']);down=float(e['lower'])
    cross=np.flatnonzero((price[:np.searchsorted(ts,minute+M)]>up)|(price[:np.searchsorted(ts,minute+M)]<down))
    if not len(cross):return {'status':'missing_first_cross'}
    c=int(cross[0]);direction=1 if price[c]>up else -1
    if int(ts[c])!=int(e['decision_ts']) or direction!=side or not np.isclose(price[c],e['signal_close'],rtol=1e-11,atol=1e-12):return {'status':'cross_mismatch'}
    i5=int(np.searchsorted(ts,int(e['decision_ts'])+DELAY))
    if i5>=len(ts):return {'status':'missing_p5'}
    if int(ts[i5])!=int(e['entry_exec_ts']) or not np.isclose(price[i5],e['raw_entry_5s'],rtol=1e-11,atol=1e-12):return {'status':'p5_mismatch'}
    i10=int(np.searchsorted(ts,int(ts[i5])+DELAY))
    if i10>=len(ts):return {'status':'missing_p10'}
    if int(ts[i10])!=int(e['second_ref_ts']) or not np.isclose(price[i10],e['second_ref_price'],rtol=1e-11,atol=1e-12):return {'status':'p10_mismatch'}
    if side*(price[i10]-price[i5])>=0 or side*(price[i10]-float(e['level']))<=0:return {'status':'pullback_condition_mismatch'}
    if known_precheck(e,leverage) is not None:return {'status':'p5_precheck_mismatch'}
    new={**e,'entry_exec_ts':int(ts[i10]),'raw_entry_5s':float(price[i10])}
    if known_precheck(new,leverage) is not None:return {'status':'p10_precheck_mismatch'}
    i=int(np.searchsorted(ts,int(ts[i10])+DELAY))
    if i>=len(ts):return {'status':'missing_delayed_entry'}
    entry_ts=int(ts[i]);entry_raw=float(price[i]);entry=entry_raw*(1+side*SLIP)
    if entry_ts>=end:return {'status':'entry_after_quarter_end','entry_ts':entry_ts}
    stop=float(e['stop_price']);dist=side*(entry-stop);atr=float(e['atr']);trigger=float(e['signal_close'])
    invalid=(dist<=0 or dist>1.5*atr or side*(entry-trigger)>.25*atr or dist/entry+.003>=.5*(1/leverage-.01))
    if invalid:signal=entry_ts;reason='filled_beyond_risk_budget'
    else:
        target=entry+side*2*dist;last=int(np.searchsorted(ts,end,side='right'));t=ts[i:last];p=price[i:last]
        candidates=[(end,3,'quarter_time')];stops=np.flatnonzero(side*(p-stop)<=0);targets=np.flatnonzero(side*(p-target)>=0)
        if len(stops):candidates.append((int(t[stops[0]]),0,'stop'))
        if len(targets):candidates.append((int(t[targets[0]]),1,'target'))
        if fast_fail and len(p):
            inside=side*(p-float(e['level']))<=0;begins=inside&~np.r_[False,inside[:-1]]
            starts=np.maximum.accumulate(np.where(begins,t,0));fails=np.flatnonzero(inside&((t-starts)>=FAIL))
            if len(fails):candidates.append((int(t[fails[0]]),2,'failed_breakout'))
        signal,_,reason=min(candidates)
    j=int(np.searchsorted(ts,signal+DELAY))
    if j>=len(ts):return {'status':'missing_delayed_exit','entry_ts':entry_ts,'exit_signal_ts':signal}
    raw=float(price[j]);return {'status':'verified','entry_ts':entry_ts,'entry_raw':entry_raw,'entry_fill':entry,
      'entry_signal_reference_ts':int(ts[i10]),'exit_signal_ts':signal,'exit_ts':int(ts[j]),'exit_raw':raw,
      'exit_fill':raw*(1-side*SLIP),'reason':reason,'initial_stop':stop,'target_r':2.,'fast_fail':fast_fail,
      'actual_entry_risk':dist}
