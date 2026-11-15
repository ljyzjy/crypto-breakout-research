"""Reconstruct timestamps, learned coefficients, predictions and account legs."""
import hashlib,json,math
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from features import FEATURES
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
model=json.loads((HERE/'固定大柱预判模型.json').read_text(encoding='utf-8'))
train=pd.read_parquet(HERE/'训练特征与事后大柱标签.parquet')
test=pd.read_parquet(HERE/'2026冻结模型预测与事后标签.parquet')
assert model['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert model['training_sha256']==hashlib.sha256((HERE/'训练特征与事后大柱标签.parquet').read_bytes()).hexdigest()
assert model['training_events']==len(train) and model['training_large_events']==int(train.large_1pct_label.astype(bool).sum())
assert (train.quarter_end<=model['cutoff_utc_ms']).all() and train.entry_exec_ts.max()<test.entry_exec_ts.min()
for d in [train,test]:
    assert d.observation_id.is_unique and (d.window_end<=d.entry_exec_ts).all()
    assert (d.first_ts>d.decision_ts).all() and (d.last_ts<d.window_end).all()
    assert (d.side*(d.raw_entry_5s-d.level)>0).all() and d.flow_count.ge(3).all()
    for r in d.itertuples(index=False):
        expected=[r.side*r.prior_body_atr,np.log1p(r.prior_prefix_ratio),r.atr/r.level,
          (r.decision_ts-r.quarter_start)/1000,r.side*(r.raw_entry_5s-r.signal_close)/r.atr,
          r.directional_imbalance,np.log1p(r.total_notional/r.previous_quote)]
        assert np.allclose([getattr(r,k) for k in FEATURES],expected,rtol=1e-11,atol=1e-12)
    for (year,contract),g in d.groupby(['source_year','contract']):
        norm=ROOT/'work'/('breakout_november_2026' if year=='2026' else 'breakout_2024_11')/'normalized'
        raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','quote_volume']).set_index('ts')
        actual=raw.reindex(g.quarter_start.to_numpy('int64')-60_000).quote_volume.to_numpy(float)
        assert np.allclose(g.previous_quote.to_numpy(float),actual,rtol=1e-11)
mean=train[FEATURES].to_numpy(float).mean(axis=0);scale=train[FEATURES].to_numpy(float).std(axis=0);scale[scale<1e-12]=1.
assert np.allclose(mean,model['mean']) and np.allclose(scale,model['scale'])
x=np.clip((train[FEATURES].to_numpy(float)-mean)/scale,-5,5);X=np.column_stack([np.ones(len(x)),x])
y=train.large_1pct_label.astype(bool).to_numpy(float)
def objective(beta):
    z=X@beta;value=np.mean(np.logaddexp(0,z)-y*z)+.1*np.dot(beta[1:],beta[1:])
    grad=X.T@(expit(z)-y)/len(y);grad[1:]+=.2*beta[1:];return value,grad
fit=minimize(objective,np.zeros(X.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12})
assert fit.success and np.allclose(fit.x,model['coefficients'],rtol=1e-9,atol=1e-10)
v=np.clip((test[FEATURES].to_numpy(float)-mean)/scale,-5,5)
pred=expit(np.column_stack([np.ones(len(v)),v])@np.array(model['coefficients']))
assert np.allclose(pred,test.predicted_large_probability,rtol=1e-11) and np.array_equal(pred>=.3,test.model_selected.to_numpy(bool))
idx=test.set_index('observation_id');accounts=trades=partials=0
for path in HERE.glob('model_2026_*_summary.json'):
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    ts=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    es=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    fs=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(ts)==len(es)==sm['trades']
    assert abs(sm['net_pnl']-sum(t['net'] for t in ts))<1e-7
    assert abs(sum(t['funding'] for t in ts)-sum(f['actual_charge'] for f in fs))<1e-7
    eq=np.r_[1000.,curve.equity.to_numpy()];assert np.isclose(np.max(100*(1-eq/np.maximum.accumulate(eq))),sm['max_drawdown'])
    for t in ts:
        r=idx.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert r.model_selected and r.predicted_large_probability>=.3 and t['entry_ts']==r.entry_exec_ts
        q=t['qty'];part=t['partial_qty'];end=q-part;fee=sm['fee'];slip=sm['slippage']
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*slip),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['final_fill'],t['final_raw_exit']*(1-side*(slip+extra)),rtol=1e-11)
        if part:
            partials+=1;assert np.isclose(part,.5*q) and t['partial_ts']>=t['partial_known_ts']+60_000
            assert np.isclose(t['partial_fill'],t['partial_raw_exit']*(1-side*slip),rtol=1e-11)
        expected=side*(part*(t['partial_fill']-t['entry'])+end*(t['final_fill']-t['entry']))-t['entry_fee']-t['exit_fee']-t['funding']
        assert np.isclose(expected,t['net'],atol=1e-8)
    accounts+=1;trades+=len(ts)
out={'training_feature_rows':len(train),'prediction_rows':len(test),'accounts_checked':accounts,
     'trade_records_checked':trades,'partial_exits_checked':partials,'refit_matches_frozen_model':True,
     'checks':'training labels known by cutoff, prior-minute volume, causal 5-second features, predictions, account and fees'}
(HERE/'大柱模型独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('BIGBAR_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
