"""Verify fast-failure timing, original controls, and account arithmetic."""
import json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;PARENT=HERE.parent;M=60_000
sig=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
sig=sig[sig.status.eq('verified')&sig.source_year.eq('2026')].set_index('observation_id')
ft=pd.read_parquet(PARENT/'第十九轮_突破后五秒主动成交'/'五秒主动成交特征_2026.parquet').set_index('observation_id')
accounts=trades=events=0
for p in HERE.glob('screen_*_summary.json'):
    sm=json.loads(p.read_text(encoding='utf-8'));stem=p.name.removesuffix('_summary.json')
    ts=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    es=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    fs=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(ts)==len(es)==sm['trades']
    assert abs(sm['net_pnl']-sum(t['net'] for t in ts))<1e-7
    assert abs(sum(t['funding'] for t in ts)-sum(x['actual_charge'] for x in fs))<1e-7
    eq=np.r_[1000.,curve.equity.to_numpy()];assert abs(np.max(100*(1-eq/np.maximum.accumulate(eq)))-sm['max_drawdown'])<1e-8
    rmap={x['id']:x for x in sm['rule_events'] if x['kind']=='failure_scheduled'}
    assert len(rmap)==len(sm['rule_events'])
    for t in ts:
        r=sig.loc[t['observation_id']];x=ft.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert x.status=='verified' and x['count']>=3 and x.directional_imbalance>=.1
        assert side*(r.raw_entry_5s-r.level)>0 and t['entry_ts']==r.entry_exec_ts>=r.decision_ts+5000
        if t['failure_known_ts']:
            event=rmap[t['observation_id']];assert event['known_ts']==t['failure_known_ts']
            assert event['effective_ts']==event['known_ts']+M and side*(event['close']-event['level'])<=0
            assert t['entry_ts']<event['known_ts']<=t['exit_ts']
            if t['reason']=='failed_breakout':assert t['exit_ts']==event['effective_ts']
        else:assert t['observation_id'] not in rmap
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(sm['slippage']+extra)),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
    if '_control_' in stem:
        oldstem=stem.replace('_control_','_flow5_strong_')
        old=json.loads((PARENT/'第十九轮_突破后五秒主动成交'/f'{oldstem}_trades.json').read_text(encoding='utf-8'))
        assert len(old)==len(ts)
        for a,b in zip(ts,old):
            for k in ('observation_id','entry_ts','exit_ts','reason','net','qty','funding'):
                assert (a[k]==b[k] if isinstance(a[k],str) else np.isclose(a[k],b[k],atol=1e-9)),(stem,k)
    accounts+=1;trades+=len(ts);events+=len(rmap)
out={'accounts_checked':accounts,'trade_records_checked':trades,'scheduled_failure_events':events,
     'checks':'known-close ordering, one-minute delay, original-stop priority, ledger and matched controls'}
(HERE/'快速失败独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('QUICKFAIL_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
