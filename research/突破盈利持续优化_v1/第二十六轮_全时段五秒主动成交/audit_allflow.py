"""Audit cohort union, causal prior-minute flow, partial legs and account paths."""
import hashlib,json,math
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;M=60_000
data=pd.read_parquet(HERE/'全时段五秒特征候选.parquet');assert data.observation_id.is_unique
assert not data.duplicated(['symbol','quarter_start']).any()
assert (data.entry_exec_ts>=data.decision_ts+5000).all() and (data.entry_exec_ts<data.quarter_end).all()
assert (data.previous_flow_known_ts==data.trigger_minute).all() and (data.feature_known_ts<=data.decision_ts).all()
assert (data.loc[data.cohort.eq('opening'),'trigger_minute']==data.loc[data.cohort.eq('opening'),'quarter_start']).all()
assert (data.loc[data.cohort.eq('later'),'trigger_minute']>data.loc[data.cohort.eq('later'),'quarter_start']).all()
v=data[data.five_status.eq('verified')]
assert (v.first_ts>v.decision_ts).all() and (v.last_ts<v.window_end).all() and (v.window_end<=v.entry_exec_ts).all()
assert (v.flow_archive_sha==v.archive_sha256).all()
assert np.allclose(v.total_notional,v.buy_notional+v.sell_notional,rtol=1e-11)
assert np.allclose(v.five_imbalance,v.side*(v.buy_notional-v.sell_notional)/v.total_notional,rtol=1e-11,atol=1e-12)
checked=0
for (year,contract),g in data.groupby(['source_year','contract']):
    folder='breakout_november_2026' if year=='2026' else 'breakout_2024_11'
    raw=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{contract}_klines.parquet',columns=['ts','quote_volume','taker_buy_quote_volume']).set_index('ts')
    prev=raw.reindex(g.trigger_minute.to_numpy('int64')-M);v=prev.quote_volume.to_numpy(float);b=prev.taker_buy_quote_volume.to_numpy(float)
    expected=g.side.to_numpy(float)*(2*b/v-1);actual=g.previous_signed_flow.to_numpy(float)
    assert np.allclose(actual,expected,rtol=1e-11,atol=1e-12,equal_nan=True);checked+=len(g)
choice=json.loads((HERE/'全时段五秒冻结决定.json').read_text(encoding='utf-8'))
assert choice['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert choice['training_sha256']==hashlib.sha256((HERE/'前四月训练候选.json').read_bytes()).hexdigest()
train=json.loads((HERE/'前四月训练候选.json').read_text(encoding='utf-8'))
viable=[s for s in train if s['valid_for_comparison'] and s['trades']>=30]
passed=[s for s in viable if s['net_win_rate_pct'] is not None and s['net_win_rate_pct']>=60 and s['net_pnl']>0 and s['profit_factor'] is not None and s['profit_factor']>1]
assert bool(passed)==choice['training_passed'] and max(passed or viable,key=lambda x:x['net_pnl'])['run_id']==choice['selected']
idx=data.set_index('observation_id');near=lambda a,b:math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
accounts=records=partials=0
for path in HERE.glob('*_summary.json'):
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    ts=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    es=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    fs=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(ts)==len(es)==sm['trades']
    assert near(sm['net_pnl'],sum(t['net'] for t in ts)) and near(sum(t['funding'] for t in ts),sum(f['actual_charge'] for f in fs))
    eq=np.r_[1000.,curve.equity.to_numpy()];assert near(np.max(100*(1-eq/np.maximum.accumulate(eq))),sm['max_drawdown'])
    for t in ts:
        r=idx.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert side*(r.raw_entry_5s-r.level)>0 and t['entry_ts']==r.entry_exec_ts
        assert r.five_status=='verified' and r.five_count>=3 and r.five_imbalance>=.1
        if '_preflow_' in stem:assert r.previous_signed_flow>=.1
        if '_follow_' in stem:assert side*(r.raw_entry_5s-r.signal_close)>0
        q=t['qty'];part=t['partial_qty'];end=q-part;fee=sm['fee'];slip=sm['slippage']
        assert near(t['entry_fee'],q*t['entry']*fee) and near(t['entry'],t['raw_entry']*(1+side*slip))
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert near(t['final_fill'],t['final_raw_exit']*(1-side*(slip+extra)))
        assert near(t['final_exit_fee'],end*t['final_fill']*fee+t['liquidation_penalty'])
        if part:
            partials+=1;assert near(part,.5*q) and t['partial_ts']>=t['partial_known_ts']+M
            assert near(t['partial_fill'],t['partial_raw_exit']*(1-side*slip)) and near(t['partial_exit_fee'],part*t['partial_fill']*fee)
            assert near(t['stop'],t['entry']+side*.25*t['initial_price_risk'])
        expected=side*(part*(t['partial_fill']-t['entry'])+end*(t['final_fill']-t['entry']))-t['entry_fee']-t['exit_fee']-t['funding']
        assert near(expected,t['net']) and near(t['exit_fee'],t['partial_exit_fee']+t['final_exit_fee'])
    accounts+=1;records+=len(ts)
out={'signal_feature_rows':checked,'accounts_checked':accounts,'trade_records_checked':records,
     'partial_exits_checked':partials,'training_selection_reproduced':True,
     'scope':'Known-before-trigger flow, 5s reference, delayed partial exits, cost/ledger and drawdown.'}
(HERE/'全时段五秒独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('ALLFLOW_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
