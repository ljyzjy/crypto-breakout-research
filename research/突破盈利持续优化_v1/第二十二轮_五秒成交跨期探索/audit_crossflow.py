"""Reconcile partial legs, 5-second gating and prior no-partial controls."""
import json,math
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
sig=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
sig=sig[sig.status.eq('verified')&sig.source_year.eq('2024')].set_index('observation_id')
ft=pd.read_parquet(HERE/'五秒主动成交特征_2024.parquet').set_index('observation_id')
assert sig.index.is_unique and ft.index.is_unique and set(sig.index)==set(ft.index)
for ix,x in ft.iterrows():
    r=sig.loc[ix]
    if x.status=='verified':
        assert r.decision_ts<x.first_ts<=x.last_ts<r.decision_ts+5000<=r.entry_exec_ts
        assert np.isclose(x.total_notional,x.buy_notional+x.sell_notional,rtol=1e-12)
        assert np.isclose(x.directional_imbalance,r.side*(x.buy_notional-x.sell_notional)/x.total_notional,rtol=1e-12)
near=lambda a,b:math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
accounts=trades=partials=0
for path in HERE.glob('cross_2024_*_summary.json'):
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    ts=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    es=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    fs=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(ts)==len(es)==sm['trades']
    assert near(sm['net_pnl'],sum(t['net'] for t in ts))
    assert near(sum(t['funding'] for t in ts),sum(x['actual_charge'] for x in fs))
    eq=np.r_[1000.,curve.equity.to_numpy()];assert near(np.max(100*(1-eq/np.maximum.accumulate(eq))),sm['max_drawdown'])
    for t in ts:
        r=sig.loc[t['observation_id']];x=ft.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert x.status=='verified' and x['count']>=3 and x.directional_imbalance>=.1
        assert side*(r.raw_entry_5s-r.level)>0 and t['entry_ts']==r.entry_exec_ts>=r.decision_ts+5000
        q=t['qty'];part=t['partial_qty'];end=q-part;fee=sm['fee'];slip=sm['slippage']
        assert near(t['entry_fee'],q*t['entry']*fee) and near(t['entry'],t['raw_entry']*(1+side*slip))
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert near(t['final_fill'],t['final_raw_exit']*(1-side*(slip+extra)))
        assert near(t['final_exit_fee'],end*t['final_fill']*fee+t['liquidation_penalty'])
        if part:
            partials+=1;assert near(part,.5*q) and t['partial_ts']>=t['partial_known_ts']+60_000
            assert near(t['partial_fill'],t['partial_raw_exit']*(1-side*slip)) and near(t['partial_exit_fee'],part*t['partial_fill']*fee)
            assert near(t['stop'],t['entry']+side*.25*t['initial_price_risk'])
        expected=side*(part*(t['partial_fill']-t['entry'])+end*(t['final_fill']-t['entry']))-t['entry_fee']-t['exit_fee']-t['funding']
        assert near(expected,t['net']) and near(t['exit_fee'],t['partial_exit_fee']+t['final_exit_fee'])
    accounts+=1;trades+=len(ts)
out={'feature_rows':len(ft),'accounts_checked':accounts,'trade_records_checked':trades,'partial_exits_checked':partials,
     'checks':'5-second timing and directional filter, partial timing and both exit legs, funding and ledger'}
(HERE/'跨期账户独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('CROSSFLOW_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
