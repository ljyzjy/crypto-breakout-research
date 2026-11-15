"""One-time, causal 30s progress check for an already established raw path."""
from bisect import bisect_left
from decimal import Decimal


def apply(path, prices):
    entry_ts=int(path['entry_ts']); original_ts=int(path['exit_signal_ts']); threshold=entry_ts+30000
    if original_ts<=threshold:return {'action':'original','reason':'original_signal_first'}
    times=[int(t) for t,_ in prices]
    if any(a>b for a,b in zip(times,times[1:])):raise ValueError('unordered_trade_times')
    pos=bisect_left(times,threshold)
    if pos>=len(times):return {'action':'unknown','reason':'missing_check_trade'}
    observed_ts,observed_price=times[pos],float(prices[pos][1])
    if observed_ts>=original_ts:return {'action':'original','reason':'original_signal_first'}
    side=int(path['side']);entry=Decimal(str(path['entry_fill']));risk=Decimal(str(path['actual_entry_risk']))
    if side not in (-1,1) or risk<=0:raise ValueError('invalid_entry_risk')
    progress=Decimal(side)*(Decimal(str(observed_price))-entry)/risk
    if progress>=Decimal('.25'):return {'action':'original','reason':'progress_sufficient','check_ts':observed_ts,'progress_r':float(progress)}
    out=bisect_left(times,observed_ts+5000)
    if out>=len(times):return {'action':'unknown','reason':'missing_delayed_exit','check_ts':observed_ts,'progress_r':float(progress)}
    exit_ts,raw=times[out],float(prices[out][1])
    return {'action':'early_exit','reason':'insufficient_30s_progress','check_ts':observed_ts,'progress_r':float(progress),
            'exit_signal_ts':observed_ts,'exit_ts':exit_ts,'exit_raw':raw,'exit_fill':raw*(1-side*.0005)}
