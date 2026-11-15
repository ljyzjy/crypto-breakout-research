"""Check actual scenario costs, partial accounting, and original 5bp parity."""
import json,math
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
sig=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
sig=sig[sig.status.eq('verified')].set_index('observation_id')
ft=pd.concat([pd.read_parquet(PARENT/'第二十二轮_五秒成交跨期探索'/'五秒主动成交特征_2024.parquet'),
              pd.read_parquet(PARENT/'第十九轮_突破后五秒主动成交'/'五秒主动成交特征_2026.parquet')],ignore_index=True).set_index('observation_id')
near=lambda a,b:math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
accounts=records=partials=parity=0
for path in HERE.glob('slip*_*_summary.json'):
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    ts=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    es=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    fs=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    slip={'slip2bp':.0002,'slip5bp':.0005,'slip10bp':.001}[stem.split('_')[0]]
    assert sm['fee']==.0005 and sm['slippage']==slip and sm['valid_for_comparison']
    assert len(curve)==sm['expected_calendar_minutes'] and len(ts)==len(es)==sm['trades']
    assert near(sm['net_pnl'],sum(t['net'] for t in ts)) and near(sum(t['funding'] for t in ts),sum(f['actual_charge'] for f in fs))
    eq=np.r_[1000.,curve.equity.to_numpy()];assert near(np.max(100*(1-eq/np.maximum.accumulate(eq))),sm['max_drawdown'])
    for t in ts:
        r=sig.loc[t['observation_id']];x=ft.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert x.status=='verified' and x['count']>=3 and x.directional_imbalance>=.1
        assert side*(r.raw_entry_5s-r.level)>0 and t['entry_ts']==r.entry_exec_ts>=r.decision_ts+5000
        q=t['qty'];part=t['partial_qty'];end=q-part;fee=sm['fee']
        assert near(t['entry'],t['raw_entry']*(1+side*slip)) and near(t['entry_fee'],q*t['entry']*fee)
        assert near(t['entry_slippage'],q*abs(t['entry']-t['raw_entry']))
        assert near(t['final_fill'],t['final_raw_exit']*(1-side*slip))
        assert near(t['final_exit_fee'],end*t['final_fill']*fee+t['liquidation_penalty'])
        assert near(t['final_exit_slip'],end*abs(t['final_fill']-t['final_raw_exit']))
        if part:
            partials+=1;assert near(part,.5*q) and t['partial_ts']>=t['partial_known_ts']+60_000
            assert near(t['partial_fill'],t['partial_raw_exit']*(1-side*slip)) and near(t['partial_exit_fee'],part*t['partial_fill']*fee)
            assert near(t['partial_exit_slip'],part*abs(t['partial_fill']-t['partial_raw_exit']))
        expected=side*(part*(t['partial_fill']-t['entry'])+end*(t['final_fill']-t['entry']))-t['entry_fee']-t['exit_fee']-t['funding']
        assert near(expected,t['net']) and near(t['exit_fee'],t['partial_exit_fee']+t['final_exit_fee'])
    if stem.startswith('slip5bp_'):
        lev=int(sm['position_leverage']);is_2024='_h1_2024_' in stem;is_partial='_fixed_partial_2r_' in stem
        if is_2024:
            folder=PARENT/'第二十二轮_五秒成交跨期探索';name='cross_partial_2r' if is_partial else 'cross_plain_1r';prefix='cross_2024'
        elif is_partial:
            folder=PARENT/'第二十一轮_五秒成交与分批保护';name='combined_partial_2r';prefix='screen_2026'
        else:
            folder=PARENT/'第十九轮_突破后五秒主动成交';name='flow5_strong_1r';prefix='screen_2026'
        old=json.loads((folder/f'{prefix}_{name}_{lev}x_main_trades.json').read_text(encoding='utf-8'))
        assert len(old)==len(ts)
        for a,b in zip(ts,old):
            for k in ('observation_id','entry_ts','exit_ts','reason','net','qty','funding'):
                assert (a[k]==b[k] if isinstance(a[k],str) else near(a[k],b[k])),(stem,k)
        parity+=1
    accounts+=1;records+=len(ts)
out={'accounts_checked':accounts,'trade_records_checked':records,'partial_exits_checked':partials,
     'original_5bp_parity_cases':parity,'checks':'positive scenario slippage, fee, partial legs, account equity and baseline parity',
     'limit':'Assumed slippage; not measured real executions.'}
(HERE/'滑点敏感性独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('SLIPPAGE_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
