"""Causal tick-level entry delay and first-trigger market-exit path simulation."""
import numpy as np
M=60_000;FEE=.0005;SLIP=.0005;EXTRA_DELAY=5_000;FAIL_CONFIRM=2_000
def known_precheck(e):
    """Use only the first observable 5s reference; no later price is inspected."""
    side=int(e['side']);ref=float(e['raw_entry_5s']);ref_ts=int(e['entry_exec_ts'])
    if ((ref_ts//M+480)%1440)>=1320:return 'late_day_known'
    if ref_ts+EXTRA_DELAY>=int(e['quarter_end']):return 'insufficient_candle_time_known'
    estimate=ref*(1+side*SLIP);stop=float(e['stop_price']);atr=float(e['atr']);trigger=float(e['signal_close'])
    distance=side*(estimate-stop);signal_distance=side*(trigger-stop)
    if side*(estimate-trigger)>.25*atr:return 'reference_deviation_known'
    if distance<=0 or distance>1.5*atr or 2*distance/estimate<.006 or 2*signal_distance/trigger<.006:
        return 'reference_risk_or_cost_known'
    if distance/estimate+.002+FEE+SLIP>=.5*(1/20-.005-.005):return 'reference_liquidation_buffer_known'
    return None
def simulate_path(e,ticks,target_r,fast_fail):
    """Input ticks must be sorted by (transact_time, agg_trade_id)."""
    side=int(e['side']);ts=ticks.transact_time.to_numpy(np.int64);prices=ticks.price.to_numpy(float)
    if len(ts)==0 or not np.isfinite(prices).all() or (prices<=0).any() or np.any(ts[1:]<ts[:-1]):
        return {'status':'bad_tape'}
    minute=int(e['trigger_minute']);qend=int(e['quarter_end']);upper=float(e['upper']);lower=float(e['lower'])
    first_end=np.searchsorted(ts,minute+M,side='left')
    crosses=np.flatnonzero((prices[:first_end]>upper)|(prices[:first_end]<lower))
    if len(crosses)==0:return {'status':'missing_first_cross'}
    c=int(crosses[0]);cross_side=1 if prices[c]>upper else -1
    if int(ts[c])!=int(e['decision_ts']) or cross_side!=side or not np.isclose(prices[c],float(e['signal_close']),rtol=1e-11,atol=1e-12):
        return {'status':'cross_mismatch'}
    reference=int(np.searchsorted(ts,int(e['decision_ts'])+5000,side='left'))
    if reference>=len(ts):return {'status':'missing_first_reference'}
    if int(ts[reference])!=int(e['entry_exec_ts']) or not np.isclose(prices[reference],float(e['raw_entry_5s']),rtol=1e-11,atol=1e-12):
        return {'status':'reference_mismatch'}
    fill_index=int(np.searchsorted(ts,int(ts[reference])+EXTRA_DELAY,side='left'))
    if fill_index>=len(ts):return {'status':'missing_delayed_entry'}
    entry_ts=int(ts[fill_index]);entry_raw=float(prices[fill_index]);entry=entry_raw*(1+side*SLIP)
    if entry_ts>=qend:return {'status':'entry_after_quarter_end','entry_ts':entry_ts}
    stop=float(e['stop_price']);distance=side*(entry-stop);trigger=float(e['signal_close']);atr=float(e['atr'])
    out_of_buffer=(distance<=0 or distance>1.5*atr or side*(entry-trigger)>.25*atr or
                   distance/entry+.002+FEE+SLIP>=.5*(1/20-.005-.005))
    stop_reason='filled_beyond_risk_budget' if out_of_buffer else None
    if stop_reason:
        signal_ts=entry_ts;reason=stop_reason
    else:
        target=entry+side*target_r*distance
        end=int(np.searchsorted(ts,qend,side='right'))
        times=ts[fill_index:end];p=prices[fill_index:end]
        candidates=[(qend,3,'quarter_time')]
        stops=np.flatnonzero(side*(p-stop)<=0)
        targets=np.flatnonzero(side*(p-target)>=0)
        if len(stops):candidates.append((int(times[stops[0]]),0,'stop'))
        if len(targets):candidates.append((int(times[targets[0]]),1,'target'))
        if fast_fail and len(p):
            inside=side*(p-float(e['level']))<=0
            begins=inside&~np.r_[False,inside[:-1]]
            starts=np.maximum.accumulate(np.where(begins,times,0))
            fails=np.flatnonzero(inside&((times-starts)>=FAIL_CONFIRM))
            if len(fails):candidates.append((int(times[fails[0]]),2,'failed_breakout'))
        signal_ts,_,reason=min(candidates)
    exit_index=int(np.searchsorted(ts,signal_ts+EXTRA_DELAY,side='left'))
    if exit_index>=len(ts):return {'status':'missing_delayed_exit','entry_ts':entry_ts,'exit_signal_ts':signal_ts}
    exit_ts=int(ts[exit_index]);exit_raw=float(prices[exit_index]);exit_fill=exit_raw*(1-side*SLIP)
    return {'status':'verified','entry_ts':entry_ts,'entry_raw':entry_raw,'entry_fill':entry,
            'entry_signal_reference_ts':int(ts[reference]),'exit_signal_ts':signal_ts,'exit_ts':exit_ts,
            'exit_raw':exit_raw,'exit_fill':exit_fill,'reason':reason,'initial_stop':stop,
            'target_r':target_r,'fast_fail':fast_fail,'actual_entry_risk':distance}
