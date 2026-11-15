"""Independent ledger and feature reconciliation for the first two research rounds."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_profit_research'/'curves'
paths=[HERE,HERE/'2024反向跨期验证',HERE/'第二轮_成本空间与即时成交',
       HERE/'第二轮_成本空间与即时成交'/'2023反向跨期验证']
summaries=[p for directory in paths for p in directory.glob('*_summary.json')]
counts=0;max_dd_error=0.;max_ledger_error=0.;missing_mark_active=0
missing=[int(pd.Timestamp(f'2024-08-12 10:0{m}',tz='UTC').timestamp()*1000) for m in (2,3)]
for path in summaries:
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    trades=json.loads((path.parent/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((path.parent/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((path.parent/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(WORK/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes']
    assert len(trades)==len(entries)==sm['trades']
    eq=np.r_[1000.,curve.equity.to_numpy()]
    dd=float(np.max(100*(1-eq/np.maximum.accumulate(eq))))
    max_dd_error=max(max_dd_error,abs(dd-sm['max_drawdown']))
    max_ledger_error=max(max_ledger_error,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in funding))<1e-7
    assert sum(t['net']>0 for t in trades)==sm['winning_trade_count']
    for e in entries:
        assert e['planned_loss']<=e['known_equity']*.0025+1e-7 and e['gross_after']<=e['known_equity']*2+1e-7
    for t in trades:
        side=1 if t['side']=='long' else -1;qty=t['qty'];slip=sm['slippage'];fee=sm['fee']
        assert t['entry_ts']>=t['decision_ts']+60_000
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*slip),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(slip+extra)),rtol=1e-11)
        assert np.isclose(t['entry_fee'],qty*t['entry']*fee,rtol=1e-11)
        assert np.isclose(t['exit_fee'],qty*t['exit']*fee+t['liquidation_penalty'],rtol=1e-11)
        assert np.isclose(t['net'],side*qty*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert np.isclose(t['isolated_margin'],t['entry_notional']/sm['position_leverage'],rtol=1e-11)
        assert np.isclose(t['target'],t['entry']+side*sm['target_r']*t['initial_price_risk'],rtol=1e-11)
        counts+=1
    if sm['start']<='2024-08-12'<=sm['end']:
        active=curve[curve.ts.isin([x+60_000 for x in missing])].active_in_minute
        missing_mark_active+=int(active.sum())
assert max_dd_error<1e-8 and max_ledger_error<1e-6 and missing_mark_active==0

# Check every newly created one-minute order-flow and cost-space feature against source records.
feature_count=0
second=HERE/'第二轮_成本空间与即时成交'
for year,norm in [(2024,HERE.parent.parent/'work'/'breakout_2024_11'/'normalized'),
                  (2026,HERE.parent.parent/'work'/'breakout_november_2026'/'normalized')]:
    f=pd.read_parquet(second/f'{year}新特征与事后标签.parquet')
    assert f.observation_id.is_unique
    for contract,g in f.groupby('contract'):
        raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','quote_volume','taker_buy_quote_volume']).set_index('ts')
        d=raw.reindex(g.break_ts.to_numpy(np.int64));v=d.quote_volume.to_numpy(float);b=d.taker_buy_quote_volume.to_numpy(float)
        expected=g.side.to_numpy()*(2*b/v-1)
        assert np.allclose(expected,g.signal_minute_imbalance.to_numpy(float),rtol=1e-10,atol=1e-10,equal_nan=True)
        space=g.side*(g.signal_close-g.stop_price)/g.signal_close
        assert np.allclose(space,g.signal_stop_fraction,rtol=1e-11,atol=1e-11)
        assert (g.decision_ts==g.break_ts+60_000).all() and (g.ts==g.decision_ts+60_000).all()
        feature_count+=len(g)
report={'accounts':len(summaries),'trade_records':counts,'all_signal_feature_rows':feature_count,
        'max_drawdown_error_pct_points':max_dd_error,'max_ledger_error_usdt':max_ledger_error,
        'active_minutes_in_2024_mark_gap':missing_mark_active,
        'limit':'All account records are repeated simulations of shared historical data, not independent trades.'}
(HERE/'分钟研究独立对账.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('MINUTE_RESEARCH_AUDITED',json.dumps(report,ensure_ascii=False),flush=True)
