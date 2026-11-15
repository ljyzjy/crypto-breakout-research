"""Audit target-room gates and independent account arithmetic."""
import json,math
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
d=pd.read_parquet(HERE.parent/'第六轮_柱内首次触价'/'逐笔首次触价与五秒入场_训练.parquet')
ticks=d[d.status.eq('verified')].set_index('observation_id');assert ticks.index.is_unique
summaries=list(HERE.glob('train_*_summary.json'));checked=0;gate_error=0.
for path in summaries:
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes']
    assert len(trades)==len(entries)==sm['trades']
    assert abs(sm['net_pnl']-sum(x['net'] for x in trades))<1e-7
    assert abs(sum(x['funding'] for x in trades)-sum(x['actual_charge'] for x in funding))<1e-7
    eq=np.r_[1000.,curve.equity.to_numpy()];dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    assert abs(dd-sm['max_drawdown'])<1e-8
    for t in trades:
        raw=ticks.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        est=raw.raw_entry_5s*(1+side*.0005);room=sm['target_r']*side*(est-raw.stop_price)/est
        gate_error=max(gate_error,max(0.,.0035-room));assert room>=.0035-1e-12
        assert t['entry_ts']==raw.entry_exec_ts and t['entry_ts']>=raw.decision_ts+5000
        assert np.isclose(t['raw_entry'],raw.raw_entry_5s,rtol=1e-11)
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(sm['slippage']+extra)),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert np.isclose(t['target'],t['entry']+side*sm['target_r']*t['initial_price_risk'],rtol=1e-11)
        checked+=1
out={'accounts_checked':len(summaries),'trade_records_checked':checked,'maximum_gate_shortfall':gate_error,
     'checks':'causal tick reference, frozen cost-space gate, targets, entry/exit price, account ledger, funding, drawdown'}
(HERE/'近止盈独立对账.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('ROOM_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
