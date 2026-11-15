"""Reconcile partial legs, 5-second gating and prior no-partial controls."""
import json,math
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
sig=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
sig=sig[sig.status.eq('verified')&sig.source_year.eq('2026')].set_index('observation_id')
ft=pd.read_parquet(PARENT/'第十九轮_突破后五秒主动成交'/'五秒主动成交特征_2026.parquet').set_index('observation_id')
near=lambda a,b:math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
accounts=trades=partials=0
for path in HERE.glob('screen_*_summary.json'):
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
    if '_control_2r_' in stem:
        oldstem=stem.replace('_combined_control_2r_','_flow5_strong_2r_')
        old=json.loads((PARENT/'第十九轮_突破后五秒主动成交'/f'{oldstem}_trades.json').read_text(encoding='utf-8'))
        assert len(ts)==len(old)
        for a,b in zip(ts,old):
            for k in ('observation_id','entry_ts','exit_ts','reason','net','qty','funding'):
                assert (a[k]==b[k] if isinstance(a[k],str) else near(a[k],b[k])),(stem,k)
    accounts+=1;trades+=len(ts)
out={'accounts_checked':accounts,'trade_records_checked':trades,'partial_exits_checked':partials,
     'checks':'5-second directional filter, partial timing and both exit legs, funding, ledger, control parity'}
(HERE/'组合分批独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('COMBINED_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
