"""Independently audit timing, queue-no-fill, fees, and P&L on all replayed orders."""
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_maker_tapes_2026'/'tapes'
out=pd.read_parquet(HERE/'逐信号订单模拟.parquet')
plans=pd.read_parquet(HERE/'逐信号计划与状态.parquet').set_index('observation_id')
signals=pd.read_parquet(HERE/'计划下单候选.parquet').set_index('observation_id')
DAY=86_400_000;END=1793491200000
@lru_cache(maxsize=64)
def load_day(c,tag):return pd.read_parquet(WORK/f'{c}_{tag}.parquet')
def tape(s):
    start=int(s.ts)-30_000;end=min(int(s.ts)+63*60_000+5_000,END)
    day=start//DAY*DAY;pieces=[]
    while day<end:
        tag=pd.Timestamp(day,unit='ms',tz='UTC').strftime('%Y-%m-%d')
        pieces.append(load_day(s.contract,tag));day+=DAY
    d=pd.concat(pieces,ignore_index=True)
    return d[(d.transact_time>=start)&(d.transact_time<end)].sort_values(['transact_time','agg_trade_id'])

checked=0;filled=0;no_fill_checked=0;max_error=0.
for row in out.itertuples(index=False):
    s=signals.loc[row.observation_id];p=plans.loc[row.observation_id]
    assert p.status=='ready' and row.planned_notional<=250+1e-10 and row.planned_qty>0
    c=tape(s);prior=c[c.transact_time<row.submit_ts]
    assert len(prior) and row.submit_ts-int(prior.transact_time.iloc[-1])<=30_000
    assert np.isclose(float(prior.price.iloc[-1]),row.reference,rtol=1e-12,atol=1e-12)
    if row.status=='filled':
        filled+=1;side=int(s.side)
        assert row.first_fill_ts>row.submit_ts+1000 and row.last_fill_ts>=row.first_fill_ts
        assert row.exit_ts>=row.first_fill_ts and 0<row.fill_fraction<=1+1e-10
        assert np.isclose(row.filled_qty/row.planned_qty,row.fill_fraction,rtol=1e-9,atol=1e-9)
        assert ((c.transact_time==row.exit_ts)&np.isclose(c.price,row.exit_raw,rtol=1e-10,atol=1e-10)).any()
        assert np.isclose(row.exit_price,row.exit_raw*(1-side*.0005),rtol=1e-12,atol=1e-12)
        if row.method=='limit':
            assert row.last_fill_ts<row.expiry_ts and np.isclose(row.entry_price,row.reference)
            assert np.isclose(row.qty_at_limit+row.qty_assumed_through,row.filled_qty,rtol=1e-9,atol=1e-9)
            assert np.isclose(row.entry_fee,row.filled_qty*row.entry_price*.0002,rtol=1e-10)
            if row.qty_assumed_through>0:
                hit=c[c.transact_time.eq(row.last_fill_ts)]
                assert any(side*(price-row.reference)<-max(1e-12,abs(row.reference)*1e-10) for price in hit.price)
        else:assert np.isclose(row.entry_fee,row.filled_qty*row.entry_price*.0005,rtol=1e-10)
        assert np.isclose(row.exit_fee,row.filled_qty*row.exit_price*.0005,rtol=1e-10)
        recalc=side*row.filled_qty*(row.exit_price-row.entry_price)-row.entry_fee-row.exit_fee-row.funding_cost
        max_error=max(max_error,abs(recalc-row.net))
        assert np.isclose(row.net_bp_per_planned_notional,row.net/row.planned_notional*10000)
    elif row.status=='unfilled_expired':
        assert row.method=='limit' and row.filled_qty==0 and row.net==0
        c=c[(c.transact_time>row.submit_ts+1000)&(c.transact_time<row.expiry_ts)]
        side=int(s.side);p0=float(row.reference);tol=max(1e-12,abs(p0)*1e-10)
        assert not (side*(c.price-p0)<-tol).any()
        opposite=c.is_buyer_maker if side==1 else ~c.is_buyer_maker
        at=(c.price-p0).abs()<=tol
        assert c.loc[at&opposite,'quantity'].sum()<=row.queue_multiple*row.planned_qty+1e-8
        no_fill_checked+=1
    checked+=1
assert max_error<1e-8
report={'simulated_order_records_checked':checked,'filled_records_checked':filled,
        'unfilled_queue_checks':no_fill_checked,'max_net_recalculation_error':max_error,
        'limits':'Tape and price-time queue assumptions remain shared; this is arithmetic and event-timing QA, not real order-book validation.'}
(HERE/'挂单回放独立核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('MAKER_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
