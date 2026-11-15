"""Causal, outcome-free implementation of the twelve registered features.

All timestamps are UTC milliseconds. Input ts is the minute OPEN. Hourly ts
is the hour CLOSE. Event features are first publishable at t0_open + 6 min.
No entry execution, labels, forward returns, account simulation, or fitting
to future outcomes is implemented here.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

M=60_000
H=60*M
D=24*H
FEATURES=['r6','residual6','efficiency6','concentration6','rv_relative60',
          'range_atr','boundary_distance','outside_fraction5','drawdown_atr',
          'recovery_fraction','quote_rvol','count_rvol']
EVENT_FEATURES=['boundary_distance','outside_fraction5','drawdown_atr','recovery_fraction']
HOURLY_FEATURES=['r6','residual6','efficiency6','concentration6','quote_rvol','count_rvol']
REQUIRED=['ts','open','high','low','close','volume','quote_volume','trade_count','taker_buy_quote_volume']


def normalize_minutes(minutes: pd.DataFrame, asof_ms: int|None=None) -> pd.DataFrame:
    """Return a dense open-time grid. Missing minutes remain NA, never forward-filled."""
    d=minutes.copy()
    if 'trade_count' not in d and 'count' in d: d=d.rename(columns={'count':'trade_count'})
    for col in REQUIRED:
        if col not in d:
            if col in ('trade_count','taker_buy_quote_volume'):d[col]=np.nan
            else:raise ValueError('Missing input column: '+col)
    d=d[REQUIRED].sort_values('ts')
    if d.ts.duplicated().any():raise ValueError('Duplicate minute open timestamps')
    if not d.empty and (d.ts.astype('int64')%M).ne(0).any():raise ValueError('Non-minute timestamp')
    if asof_ms is not None:d=d[d.ts+M<=int(asof_ms)]
    if d.empty:
        d.index=pd.DatetimeIndex([],tz='UTC',name='time')
        d['observed']=pd.Series(dtype=bool);d['minute_valid']=pd.Series(dtype=bool)
        return d
    d.index=pd.to_datetime(d.ts,unit='ms',utc=True);d.index.name='time'
    d['observed']=True
    d=d.reindex(pd.date_range(d.index.min(),d.index.max(),freq='min',name='time'))
    d['ts']=d.index.as_unit('ms').asi8
    d['observed']=d.observed.fillna(False).astype(bool)
    finite=np.isfinite(d[['open','high','low','close','volume','quote_volume']]).all(axis=1)
    price=d[['open','high','low','close']].gt(0).all(axis=1)
    geometry=d.high.ge(d[['open','close','low']].max(axis=1))&d.low.le(d[['open','close','high']].min(axis=1))
    d['minute_valid']=d.observed&finite&price&geometry&d.volume.gt(0)&d.quote_volume.gt(0)
    return d


def _aggregate(d: pd.DataFrame, minutes: int, asof_ms: int|None=None) -> pd.DataFrame:
    """Aggregate complete bars only; invalid input bars invalidate that entire bar."""
    if d.empty:return pd.DataFrame(index=pd.DatetimeIndex([],tz='UTC'))
    rule=f'{minutes}min'
    a=d[['open','high','low','close','volume','quote_volume','trade_count','taker_buy_quote_volume']].where(d.minute_valid,axis=0)
    g=a.resample(rule,label='right',closed='left')
    out=g.agg({'open':'first','high':'max','low':'min','close':'last'})
    out['valid_count']=d.minute_valid.resample(rule,label='right',closed='left').sum()
    out['valid']=out.valid_count.eq(minutes)
    for col in ['volume','quote_volume','trade_count','taker_buy_quote_volume']:
        out[col]=g[col].sum(min_count=minutes)
    out.loc[~out.valid,['open','high','low','close','volume','quote_volume','trade_count','taker_buy_quote_volume']]=np.nan
    available=int(d.ts.iloc[-1])+M if asof_ms is None else int(asof_ms)
    out=out[out.index.as_unit('ms').asi8<=available]
    return out


def historical_same_phase_median(series: pd.Series, periods_per_day: int, days: int=20) -> pd.Series:
    """20 exact previous calendar-day phases; missing values cannot be skipped."""
    # All caller indexes are dense fixed-frequency grids. shift excludes current.
    lagged=pd.concat([series.shift(periods_per_day*k) for k in range(1,days+1)],axis=1)
    return lagged.median(axis=1).where(lagged.notna().all(axis=1))


def compute_hourly(minutes: pd.DataFrame, btc_hourly: pd.DataFrame|None=None,
                   is_btc: bool=False, background_hours: int=6,
                   asof_ms: int|None=None) -> pd.DataFrame:
    """Hourly features indexed by closed-hour milliseconds.

    background_hours supports only the preregistered 5/6/7 identification checks.
    The beta exclusion/fit/standardization remains fixed at 6/720/24 throughout.
    """
    if background_hours not in (5,6,7):raise ValueError('Only preregistered 5/6/7 horizons')
    d=normalize_minutes(minutes,asof_ms);a=_aggregate(d,60,asof_ms)
    cols=['ts','close','hour_valid','hourly_return','r6','residual6','residual_raw6','alpha','beta',
          'efficiency6','concentration6','quote_rvol','count_rvol','vol24','btc_r6',
          'regression_pairs','residual_variance24','taker_imbalance','source_max_open_ts','source_max_known_ts']
    if a.empty:return pd.DataFrame(columns=cols).set_index('ts',drop=False)
    out=pd.DataFrame(index=a.index);out['close']=a.close;out['hour_valid']=a.valid
    r=np.log(a.close).diff();out['hourly_return']=r
    n=background_hours;out['r6']=r.rolling(n,min_periods=n).sum()
    denominator=r.abs().rolling(n,min_periods=n).sum()
    out['efficiency6']=out.r6.abs()/denominator.where(denominator>0)
    out['concentration6']=r.abs().rolling(n,min_periods=n).max()/denominator.where(denominator>0)
    out['vol24']=r.rolling(24,min_periods=24).std(ddof=1)
    out['quote_rvol']=a.quote_volume/historical_same_phase_median(a.quote_volume,24).where(lambda x:x>0)
    count=a.trade_count.where(a.trade_count.gt(0))
    out['count_rvol']=count/historical_same_phase_median(count,24).where(lambda x:x>0)
    out['taker_imbalance']=(2*a.taker_buy_quote_volume-a.quote_volume)/a.quote_volume.where(lambda x:x>0)
    if is_btc:b=r.copy()
    elif btc_hourly is None:b=pd.Series(np.nan,index=a.index)
    else:
        bh=btc_hourly.copy()
        if 'ts' in bh:bh.index=pd.to_datetime(bh.ts,unit='ms',utc=True)
        b=bh.hourly_return.reindex(a.index)
    out['btc_r6']=b.rolling(n,min_periods=n).sum()
    paired=r.notna()&b.notna();x=b.where(paired);y=r.where(paired)
    fit_n=720;exclude=6
    vx=x.rolling(fit_n,min_periods=fit_n).var(ddof=1).shift(exclude)
    cov=y.rolling(fit_n,min_periods=fit_n).cov(x).shift(exclude)
    beta=cov/vx.where(vx>1e-16)
    alpha=y.rolling(fit_n,min_periods=fit_n).mean().shift(exclude)-beta*x.rolling(fit_n,min_periods=fit_n).mean().shift(exclude)
    r6=r.rolling(6,min_periods=6).sum();b6=b.rolling(6,min_periods=6).sum()
    raw=r6-6*alpha-beta*b6
    v24=y.rolling(24,min_periods=24).var(ddof=1)+beta.pow(2)*x.rolling(24,min_periods=24).var(ddof=1)-2*beta*y.rolling(24,min_periods=24).cov(x)
    out['alpha']=alpha;out['beta']=beta;out['residual_raw6']=raw
    out['residual_variance24']=v24
    out['residual6']=raw/np.sqrt(6*v24.where(v24>1e-20))
    if is_btc:out[['residual6','residual_raw6']]=np.nan
    out['regression_pairs']=paired.astype(int).rolling(fit_n,min_periods=fit_n).sum().shift(exclude)
    out['ts']=out.index.as_unit('ms').asi8
    out['source_max_open_ts']=out.ts-M;out['source_max_known_ts']=out.ts
    out=out.replace([np.inf,-np.inf],np.nan)
    return out.set_index('ts',drop=False)[cols]


def compute_minute_context(minutes: pd.DataFrame, asof_ms: int|None=None) -> pd.DataFrame:
    """Minute context with prior-completed-15m ATR and rolling 60m realized vol."""
    d=normalize_minutes(minutes,asof_ms)
    cols=['ts','decision_ts','minute_valid','observed','atr14','atr_known_ts','range_atr',
          'rv60','rv_relative60','zero_volume','trade_count_valid','source_max_open_ts','source_max_known_ts']
    if d.empty:return pd.DataFrame(columns=cols).set_index('ts',drop=False)
    a=_aggregate(d,15,asof_ms);prev=a.close.shift(1)
    tr=pd.concat([a.high-a.low,(a.high-prev).abs(),(a.low-prev).abs()],axis=1).max(axis=1)
    # A gap in the previous complete bar is not replaced by high-low alone.
    tr=tr.where(a.valid&prev.notna())
    atr=tr.rolling(14,min_periods=14).mean()
    # Reindex forward refers only to the latest already-CLOSED quarter, at minute OPEN.
    quarter_key=d.index.floor('15min');atr_at_open=atr.reindex(quarter_key)
    out=pd.DataFrame(index=d.index);out['ts']=d.ts;out['decision_ts']=d.ts+M
    out['minute_valid']=d.minute_valid;out['observed']=d.observed
    out['atr14']=atr_at_open.to_numpy();out['atr_known_ts']=quarter_key.as_unit('ms').asi8
    out['range_atr']=(d.high-d.low).where(d.minute_valid)/out.atr14.where(out.atr14>0)
    close=d.close.where(d.minute_valid);r=np.log(close).diff()
    rv=np.sqrt(r.pow(2).rolling(60,min_periods=60).sum())
    med=historical_same_phase_median(rv,1440)
    out['rv60']=rv;out['rv_relative60']=rv/med.where(med>0)
    out['zero_volume']=d.observed&d.volume.eq(0)
    out['trade_count_valid']=d.minute_valid&d.trade_count.gt(0)&np.isfinite(d.trade_count)
    out['source_max_open_ts']=d.ts;out['source_max_known_ts']=d.ts+M
    return out.replace([np.inf,-np.inf],np.nan).set_index('ts',drop=False)[cols]


def _eligibility(ts: np.ndarray, eligible_days: set[str]|list[str]|None) -> np.ndarray:
    if eligible_days is None:return np.ones(len(ts),dtype=bool)
    allowed={int(pd.Timestamp(day,tz='UTC').timestamp()*1000)//D for day in eligible_days}
    return np.isin(ts//D,list(allowed))


def build_event_rows(minutes: pd.DataFrame, context: pd.DataFrame|None=None,
                     eligible_days: set[str]|list[str]|None=None,
                     known_quarantine_ts: int|None=None, lookback: int=20,
                     start_ms: int|None=None,end_ms: int|None=None,
                     asof_ms: int|None=None) -> pd.DataFrame:
    """Chronological breakout queue; event occurrence never uses future success.

    A fresh close crossing is close[t] > prior_high[t] while close[t-1] <=
    prior_high[t-1] (reverse for shorts). Each symbol admits the first such
    event after a 60-minute exclusion since the last admitted breakout.
    Decisions occur at t0_open+6min; incomplete/pending events are retained.
    """
    if lookback not in (15,20,25):raise ValueError('Only preregistered 15/20/25 boundaries')
    d=normalize_minutes(minutes,asof_ms)
    cols=['event_id','t0_open_ts','t0_known_ts','decision_ts','side','B','A','atr_known_ts',
          'event_status','eligible_decision','quarantined','minute_valid','source_max_open_ts',
          'source_max_known_ts','no_confirmed_reverse_segment','breakout_reclaimed',*EVENT_FEATURES]
    if d.empty:return pd.DataFrame(columns=cols)
    if context is None:context=compute_minute_context(minutes,asof_ms)
    ctx=context.reindex(d.ts.to_numpy())
    close=d.close.where(d.minute_valid)
    high=d.high.where(d.minute_valid).rolling(lookback,min_periods=lookback).max().shift(1)
    low=d.low.where(d.minute_valid).rolling(lookback,min_periods=lookback).min().shift(1)
    long_now=close.gt(high);short_now=close.lt(low)
    fresh_long=long_now&~long_now.shift(1,fill_value=False)&high.shift(1).notna()
    fresh_short=short_now&~short_now.shift(1,fill_value=False)&low.shift(1).notna()
    times=d.ts.to_numpy(dtype=np.int64);known=times+M
    eligible=_eligibility(known,eligible_days)
    allowed=eligible&((fresh_long|fresh_short).to_numpy())
    if start_ms is not None:allowed&=known>=int(start_ms)
    if end_ms is not None:allowed&=known<int(end_ms)
    if known_quarantine_ts is not None:allowed&=known<int(known_quarantine_ts)
    actual_asof=int(times[-1]+M) if asof_ms is None else int(asof_ms)
    last_admitted=-10**18;rows=[]
    highs=d.high.to_numpy();lows=d.low.to_numpy();closes=d.close.to_numpy();valid=d.minute_valid.to_numpy()
    for j in np.flatnonzero(allowed):
        t0=int(times[j])
        if t0-last_admitted<60*M:continue
        last_admitted=t0;s=1 if fresh_long.iloc[j] else -1
        B=float(high.iloc[j] if s==1 else low.iloc[j]);A=float(ctx.atr14.iloc[j])
        decision=t0+6*M;end_j=j+5
        elig_dec=bool(_eligibility(np.array([decision]),eligible_days)[0])
        quarantined=known_quarantine_ts is not None and decision>=int(known_quarantine_ts)
        rec=dict(event_id=f'{t0}:{s}',t0_open_ts=t0,t0_known_ts=t0+M,decision_ts=decision,
                 side=s,B=B,A=A,atr_known_ts=int(ctx.atr_known_ts.iloc[j]),
                 eligible_decision=elig_dec,quarantined=bool(quarantined),minute_valid=False,
                 source_max_open_ts=np.nan,source_max_known_ts=np.nan,
                 no_confirmed_reverse_segment=False,breakout_reclaimed=False,
                 **{x:np.nan for x in EVENT_FEATURES})
        if decision>actual_asof:
            # These facts may only become knowable after the current prefix.
            rec['eligible_decision']=None;rec['quarantined']=None
            rec['event_status']='pending_measurement';rows.append(rec);continue
        if end_ms is not None and decision>=int(end_ms):
            rec['event_status']='outside_development';rows.append(rec);continue
        if end_j>=len(d) or not valid[j:end_j+1].all():
            rec['event_status']='missing_or_invalid_measurement_window';rows.append(rec);continue
        rec['minute_valid']=True;rec['source_max_open_ts']=int(times[end_j]);rec['source_max_known_ts']=decision
        if not np.isfinite(A) or A<=0:
            rec['event_status']='missing_prior_atr';rows.append(rec);continue
        oriented_high=np.maximum(s*highs[j:end_j+1],s*lows[j:end_j+1])
        oriented_low=np.minimum(s*highs[j:end_j+1],s*lows[j:end_j+1])
        P=float(oriented_high.max());last_peak=int(np.flatnonzero(oriented_high==P)[-1])
        current=float(s*closes[end_j]);recovery=0.0;no_reverse=True
        if last_peak<len(oriented_low)-1:
            W=float(oriented_low[last_peak+1:].min())
            if P>W:
                recovery=float(np.clip((current-W)/(P-W),0,1));no_reverse=False
        rec.update(boundary_distance=float(s*(closes[end_j]-B)/A),
                   outside_fraction5=float(np.mean(s*(closes[j+1:end_j+1]-B)>=.25*A)),
                   drawdown_atr=float((P-current)/A),recovery_fraction=recovery,
                   no_confirmed_reverse_segment=no_reverse,
                   breakout_reclaimed=bool(s*(closes[end_j]-B)<=0))
        rec['event_status']='quarantined_before_measurement' if quarantined else ('left_pool_before_measurement' if not elig_dec else 'measured')
        rows.append(rec)
    return pd.DataFrame(rows,columns=cols)
