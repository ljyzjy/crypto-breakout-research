"""Verify a potential minute with trade tape and make only causal signal decisions."""
import json
import numpy as np,pandas as pd
from leveraged_paths import known_precheck,simulate_path,M
def decide(e,ticks,bars):
    t=int(e['trigger_minute']);qstart=int(e['quarter_start']);qend=int(e['quarter_end'])
    if t not in bars.index:return {'status':'missing_trigger_minute'}
    prior=np.arange(qstart,t,M,dtype=np.int64)
    earlier=bars.reindex(prior)
    if len(earlier) and not np.isfinite(earlier[['high','low']].to_numpy(float)).all():return {'status':'missing_quarter_prefix'}
    if len(earlier) and ((earlier.high>e['upper']).any() or (earlier.low<e['lower']).any()):return {'status':'earlier_minute_cross_mismatch'}
    first=ticks[(ticks.transact_time>=t)&(ticks.transact_time<t+M)]
    if first.empty:return {'status':'missing_trigger_ticks'}
    b=bars.loc[t];observed=[float(first.price.iloc[0]),float(first.price.max()),float(first.price.min()),float(first.price.iloc[-1])]
    official=[float(b.open),float(b.high),float(b.low),float(b.close)]
    if not np.allclose(observed,official,rtol=1e-9,atol=1e-12):return {'status':'minute_trade_ohlc_mismatch'}
    crosses=first[(first.price>e['upper'])|(first.price<e['lower'])]
    if crosses.empty:return {'status':'minute_without_public_cross'}
    cross=crosses.iloc[0];decision=int(cross.transact_time);side=1 if float(cross.price)>e['upper'] else -1
    if not bool(e['long_known_eligible' if side==1 else 'short_known_eligible']):return {'status':'first_direction_ineligible','side':side}
    if decision+5000>=qend:return {'status':'no_order_time','side':side}
    after=ticks[ticks.transact_time>=decision+5000]
    if after.empty:return {'status':'missing_five_second_reference','side':side}
    ref=after.iloc[0];ref_ts=int(ref.transact_time)
    if ref_ts>=qend:return {'status':'no_order_time','side':side}
    window=ticks[(ticks.transact_time>decision)&(ticks.transact_time<decision+5000)]
    if len(window):
        maker=window.is_buyer_maker.astype(str).str.lower();notional=window.price.to_numpy(float)*window.quantity.to_numpy(float)
        if not maker.isin(['true','false']).all() or not np.isfinite(notional).all() or (notional<=0).any():return {'status':'invalid_flow_window'}
        buy=float(notional[maker.eq('false').to_numpy()].sum());sell=float(notional[maker.eq('true').to_numpy()].sum())
        imbalance=side*(buy-sell)/(buy+sell)
    else:buy=sell=0.;imbalance=None
    extra={'side':side,'decision_ts':decision,'signal_close':float(cross.price),'entry_exec_ts':ref_ts,
           'raw_entry_5s':float(ref.price),'five_count':len(window),'buy_notional':buy,'sell_notional':sell,
           'five_imbalance':imbalance}
    spec=json.loads(e['long_spec'] if side==1 else e['short_spec']);extra.update(spec)
    if len(window)<3 or imbalance is None or imbalance<.10 or side*(float(ref.price)-float(spec['level']))<=0:
        return {'status':'flow_filter_not_met',**extra}
    event={**e,**extra};prechecks={str(L):known_precheck(event,L) or 'passed' for L in (10,20)}
    paths={}
    for L in (10,20):
        if prechecks[str(L)]=='passed':
            for fail in (False,True):
                key=('fast_2r_' if fail else 'normal_2r_')+str(L)+'x'
                paths[key]=simulate_path(event,ticks,L,fail)
    return {'status':'qualified' if paths else 'known_risk_rejected',**extra,'prechecks':prechecks,'paths':paths}
