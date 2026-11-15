"""Causal delayed-entry/exit paths parameterized by isolated leverage."""
import numpy as np
M=60_000;FEE=.0005;SLIP=.0005;DELAY=5_000;FAIL=2_000
def known_precheck(e,leverage):
    assert leverage in (10,20)
    side=int(e['side']);ref=float(e['raw_entry_5s']);ref_ts=int(e['entry_exec_ts'])
    if ((ref_ts//M+480)%1440)>=1320:return 'late_day_known'
    if ref_ts+DELAY>=int(e['quarter_end']):return 'insufficient_candle_time_known'
    estimate=ref*(1+side*SLIP);stop=float(e['stop_price']);atr=float(e['atr']);trigger=float(e['signal_close'])
    distance=side*(estimate-stop);signal_distance=side*(trigger-stop)
    if side*(estimate-trigger)>.25*atr:return 'reference_deviation_known'
    if distance<=0 or distance>1.5*atr or 2*distance/estimate<.006 or 2*signal_distance/trigger<.006:
        return 'reference_risk_or_cost_known'
    if distance/estimate+.002+FEE+SLIP>=.5*(1/leverage-.005-.005):return 'reference_liquidation_buffer_known'
    return None
def simulate_path(e,ticks,leverage,fast_fail):
    assert leverage in (10,20)
    side=int(e['side']);ts=ticks.transact_time.to_numpy(np.int64);prices=ticks.price.to_numpy(float)
    if len(ts)==0 or not np.isfinite(prices).all() or (prices<=0).any() or np.any(ts[1:]<ts[:-1]):return {'status':'bad_tape'}
    minute=int(e['trigger_minute']);qend=int(e['quarter_end']);upper=float(e['upper']);lower=float(e['lower'])
    first_end=np.searchsorted(ts,minute+M,side='left');crosses=np.flatnonzero((prices[:first_end]>upper)|(prices[:first_end]<lower))
    if len(crosses)==0:return {'status':'missing_first_cross'}
    c=int(crosses[0]);cross_side=1 if prices[c]>upper else -1
    if int(ts[c])!=int(e['decision_ts']) or cross_side!=side or not np.isclose(prices[c],float(e['signal_close']),rtol=1e-11,atol=1e-12):return {'status':'cross_mismatch'}
    reference=int(np.searchsorted(ts,int(e['decision_ts'])+5000,side='left'))
    if reference>=len(ts):return {'status':'missing_first_reference'}
    if int(ts[reference])!=int(e['entry_exec_ts']) or not np.isclose(prices[reference],float(e['raw_entry_5s']),rtol=1e-11,atol=1e-12):return {'status':'reference_mismatch'}
    fill=int(np.searchsorted(ts,int(ts[reference])+DELAY,side='left'))
    if fill>=len(ts):return {'status':'missing_delayed_entry'}
    entry_ts=int(ts[fill]);entry_raw=float(prices[fill]);entry=entry_raw*(1+side*SLIP)
    if entry_ts>=qend:return {'status':'entry_after_quarter_end','entry_ts':entry_ts}
    stop=float(e['stop_price']);distance=side*(entry-stop);trigger=float(e['signal_close']);atr=float(e['atr'])
    invalid=(distance<=0 or distance>1.5*atr or side*(entry-trigger)>.25*atr or
             distance/entry+.002+FEE+SLIP>=.5*(1/leverage-.005-.005))
    if invalid:signal=entry_ts;reason='filled_beyond_risk_budget'
    else:
        target=entry+side*2*distance;end=int(np.searchsorted(ts,qend,side='right'));t=ts[fill:end];p=prices[fill:end]
        candidates=[(qend,3,'quarter_time')];stops=np.flatnonzero(side*(p-stop)<=0);targets=np.flatnonzero(side*(p-target)>=0)
        if len(stops):candidates.append((int(t[stops[0]]),0,'stop'))
        if len(targets):candidates.append((int(t[targets[0]]),1,'target'))
        if fast_fail and len(p):
            inside=side*(p-float(e['level']))<=0;begins=inside&~np.r_[False,inside[:-1]]
            starts=np.maximum.accumulate(np.where(begins,t,0));fails=np.flatnonzero(inside&((t-starts)>=FAIL))
            if len(fails):candidates.append((int(t[fails[0]]),2,'failed_breakout'))
        signal,_,reason=min(candidates)
    out=int(np.searchsorted(ts,signal+DELAY,side='left'))
    if out>=len(ts):return {'status':'missing_delayed_exit','entry_ts':entry_ts,'exit_signal_ts':signal}
    raw=float(prices[out]);return {'status':'verified','entry_ts':entry_ts,'entry_raw':entry_raw,'entry_fill':entry,
      'entry_signal_reference_ts':int(ts[reference]),'exit_signal_ts':signal,'exit_ts':int(ts[out]),'exit_raw':raw,
      'exit_fill':raw*(1-side*SLIP),'reason':reason,'initial_stop':stop,'target_r':2.,'fast_fail':fast_fail,
      'actual_entry_risk':distance}
