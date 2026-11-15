"""Resolve open-only OHLC differences if raw trades independently match all causal paths."""
import numpy as np,pandas as pd
from tape_decision import decide
from leveraged_paths import simulate_path,M
def reconcile(e,agg,raw,bars):
    t=int(e['trigger_minute']);qend=int(e['quarter_end'])
    if t not in bars.index:return {'reconciled':False,'reason':'missing_minute'}
    a=agg[(agg.transact_time>=t)&(agg.transact_time<t+M)]
    r=raw[(raw.transact_time>=t)&(raw.transact_time<t+M)]
    if a.empty or r.empty:return {'reconciled':False,'reason':'missing_minute_trades'}
    bar=bars.loc[t];official=[float(bar.open),float(bar.high),float(bar.low),float(bar.close)]
    def ohlc(g):return [float(g.price.iloc[0]),float(g.price.max()),float(g.price.min()),float(g.price.iloc[-1])]
    av=ohlc(a);rv=ohlc(r)
    raw_match=bool(np.allclose(rv,official,rtol=1e-9,atol=1e-12))
    only_open=bool(not np.isclose(av[0],official[0],rtol=1e-9,atol=1e-12) and np.allclose(av[1:],official[1:],rtol=1e-9,atol=1e-12))
    if not raw_match or not only_open:return {'reconciled':False,'reason':'not_open_only_or_raw_kline_mismatch','raw_matches_kline':raw_match,'aggregate_open_only':only_open}
    def crossing(g):
        z=g[(g.transact_time<t+M)&((g.price>e['upper'])|(g.price<e['lower']))]
        if z.empty:return None
        return int(z.transact_time.iloc[0]),float(z.price.iloc[0])
    ac=crossing(a);rc=crossing(r)
    if ac is None or ac!=rc:return {'reconciled':False,'reason':'first_cross_mismatch','aggregate_cross':ac,'raw_cross':rc}
    def ref(g):
        z=g[g.transact_time>=ac[0]+5000]
        return (int(z.transact_time.iloc[0]),float(z.price.iloc[0])) if len(z) else None
    ar=ref(agg);rr=ref(raw)
    if ar is None or ar!=rr:return {'reconciled':False,'reason':'five_second_reference_mismatch','aggregate_reference':ar,'raw_reference':rr}
    def flow(g):
        x=g[(g.transact_time>ac[0])&(g.transact_time<ac[0]+5000)]
        maker=x.is_buyer_maker.astype(str).str.lower()
        if not maker.isin(['true','false']).all():raise ValueError('invalid_raw_maker')
        amount=x.price.to_numpy(float)*x.quantity.to_numpy(float)
        return [float(amount[maker.eq('false').to_numpy()].sum()),float(amount[maker.eq('true').to_numpy()].sum())]
    af=flow(agg);rf=flow(raw)
    if not np.allclose(af,rf,rtol=1e-9,atol=1e-8):return {'reconciled':False,'reason':'five_second_flow_mismatch','aggregate_flow':af,'raw_flow':rf}
    patched=bars.copy();patched.loc[t,'open']=av[0]
    outcome=decide(e,agg,patched)
    valid={'qualified','flow_filter_not_met','known_risk_rejected','first_direction_ineligible','no_order_time'}
    if outcome['status'] not in valid:return {'reconciled':False,'reason':'post_reconciliation_'+outcome['status']}
    checked=[]
    if outcome['status']=='qualified':
        event={**e,**{k:v for k,v in outcome.items() if k not in ('paths','prechecks')}}
        for key,p in outcome['paths'].items():
            lev=int(key.rsplit('_',1)[1].rstrip('x'));other=simulate_path(event,raw,lev,key.startswith('fast_'))
            fields=['status','entry_ts','entry_raw','entry_fill','exit_signal_ts','exit_ts','exit_raw','exit_fill','reason']
            same=all(k in p and k in other and (np.isclose(p[k],other[k],rtol=1e-11,atol=1e-12) if isinstance(p[k],float) else p[k]==other[k]) for k in fields)
            if not same:return {'reconciled':False,'reason':'raw_aggregate_path_mismatch','variant':key,'aggregate_path':p,'raw_path':other}
            checked.append(key)
        if not checked:return {'reconciled':False,'reason':'qualified_without_path'}
    return {'reconciled':True,'original_mismatch':'minute_trade_ohlc_mismatch','resolution':'raw_confirms_open_only',
            'raw_matches_kline':True,'aggregate_open_only':True,'first_cross':ac,'five_second_reference':ar,
            'aggregate_flow':af,'raw_flow':rf,'paths_checked':checked,'outcome':outcome}
