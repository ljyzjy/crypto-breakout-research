"""Reconcile all completed account outputs against raw trade and equity records."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
Q=15*60_000; M=60_000
results=json.loads((HERE/'all_results.json').read_text(encoding='utf-8'))
assert len(results)==9
signals=pd.read_parquet(HERE/'signals.parquet').set_index('observation_id')
assert signals.index.is_unique
details=[]
for summary in results:
    name=summary['run_id']; scenario=summary['scenario']; stem=f'{name}_{scenario}'
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(HERE/f'{stem}_curve.parquet')
    assert summary['valid_for_comparison'] and len(curve)==432_000
    assert len(trades)==len(entries)==summary['trades']
    assert np.isclose(curve.equity.iloc[-1],summary['final_equity'],rtol=0,atol=1e-8)
    eq=np.r_[1000.,curve.equity.to_numpy()]
    drawdown=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    assert np.isclose(drawdown,summary['max_drawdown'],rtol=0,atol=1e-8)
    net=sum(t['net'] for t in trades)
    assert np.isclose(net,summary['net_pnl'],rtol=0,atol=1e-7)
    assert np.isclose(sum(t['funding'] for t in trades),sum(f['actual_charge'] for f in funding),rtol=0,atol=1e-7)
    same_quarter=0; entry_inside=0
    for t in trades:
        s=signals.loc[t['observation_id']]
        assert int(t['entry_ts'])>=int(s['decision_ts'])+M
        assert int(s['feature_known_ts'])<=int(s['decision_ts'])
        qend=int(s['quarter_start'])+Q
        entry_inside+=int(t['entry_ts']<qend)
        same_quarter+=int(t['exit_ts']<=qend)
        if name=='early_activity': assert bool(s['activity_pass'])
        if name=='early_sync': assert bool(s['sync_pass'])
    assert entry_inside==summary['entered_during_breakout_quarter']
    details.append({'variant':name,'scenario':scenario,'trades':len(trades),
        'entered_within_15m':entry_inside,'closed_by_15m_end':same_quarter,
        'ledger_and_drawdown_recomputed':True})
audit=json.loads((HERE/'sample_audit.json').read_text(encoding='utf-8'))
result={'all_9_accounts_reconciled':True,'all_main_entries_in_signal_quarter':
        all(x['entered_within_15m']==x['trades'] for x in details if x['scenario']=='main'),
        'independent_signal_sample_count':audit['sample_count'], 'details':details,
        'scope':'Accounting reconciliation and sampled signal reconstruction; not independent validation of exchange fills or generalization.'}
(HERE/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
