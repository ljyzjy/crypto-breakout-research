"""Reconcile all frozen-candidate later-period accounts and tick references."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROOT=HERE.parent.parent.parent
dirs={'touch':HERE,'lead':PARENT/'第八轮_BTC短时领先',
      'extended':PARENT/'第九轮_突破后延长持仓','stops':PARENT/'第十轮_结构止损与仓位'}
results=json.loads((HERE/'四种触价方案历史对照.json').read_text(encoding='utf-8'))
ticks=pd.concat([pd.read_parquet(HERE/f'逐笔首次触价与五秒入场_{tag}.parquet') for tag in ['后续','2023']],ignore_index=True)
ticks=ticks[ticks.status.eq('verified')].set_index('observation_id');assert ticks.index.is_unique
curves=ROOT/'work'/'breakout_profit_research'/'curves'
count=0;maxerr=0.;dd_err=0.;fund_count=0;gap_active=0
missing=[int(pd.Timestamp(f'2024-08-12 10:0{m}',tz='UTC').timestamp()*1000) for m in (2,3)]
for sm in results:
    directory=dirs[sm['model']]/'冻结候选历史对照'
    stem=f"{sm['period']}_{sm['run_id']}_{int(sm['position_leverage'])}x_{sm['scenario']}"
    trades=json.loads((directory/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((directory/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((directory/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(curves/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(trades)==len(entries)==sm['trades']
    eq=np.r_[1000.,curve.equity.to_numpy()];dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    dd_err=max(dd_err,abs(dd-sm['max_drawdown']))
    maxerr=max(maxerr,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in funding))<1e-7
    assert sum(t['net']>0 for t in trades)==sm['winning_trade_count']
    for e in entries:
        assert e['planned_loss']<=e['known_equity']*.0025+1e-7 and e['gross_after']<=2*e['known_equity']+1e-7
    for t in trades:
        raw=ticks.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert t['entry_ts']==raw.entry_exec_ts and t['entry_ts']>=t['decision_ts']+5000
        assert np.isclose(t['raw_entry'],raw.raw_entry_5s,rtol=1e-11)
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(sm['slippage']+extra)),rtol=1e-11)
        assert np.isclose(t['entry_fee'],t['qty']*t['entry']*sm['fee'],rtol=1e-11)
        assert np.isclose(t['exit_fee'],t['qty']*t['exit']*sm['fee']+t['liquidation_penalty'],rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert np.isclose(t['target'],t['entry']+side*sm['target_r']*t['initial_price_risk'],rtol=1e-11)
        assert t['exit_ts']<=t['entry_bar_ts']+sm['max_hold_minutes']*60_000
        count+=1
    fund_count+=len(funding)
    if sm['start']<='2024-08-12'<=sm['end']:
        gap_active+=int(curve[curve.ts.isin([x+60_000 for x in missing])].active_in_minute.sum())
assert len(results)==96 and maxerr<1e-6 and dd_err<1e-8 and gap_active==0
report={'accounts_checked':len(results),'trade_records_checked':count,'funding_events':fund_count,
        'max_ledger_error_usdt':maxerr,'max_drawdown_error_pct_points':dd_err,
        'active_minutes_in_2024_mark_gap':gap_active,'tick_references_checked':len(ticks),
        'limits':'Minute exits, fixed liquidation proxy and public-trade reference; model and time periods overlap.'}
(HERE/'后续账户独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('LATER_TOUCH_ACCOUNT_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
