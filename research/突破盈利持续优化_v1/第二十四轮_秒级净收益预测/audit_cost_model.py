"""Independently reconstruct fitting, prediction, opportunity samples and account ledgers."""
import hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from build_labels import build,FEATURES
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交',PARENT/'第六轮_柱内首次触价'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch
labels=pd.read_parquet(HERE/'2024独立机会净收益标签.parquet')
pred=pd.read_parquet(HERE/'五月六月冻结模型预测.parquet')
model=json.loads((HERE/'四月底固定净收益模型.json').read_text(encoding='utf-8'))
cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
lo=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000)
assert labels.observation_id.is_unique and pred.observation_id.is_unique
assert model['cutoff_ts']==cutoff and (pred.decision_ts>=lo).all()
train=labels[(labels.entry_ts<cutoff)&(labels.exit_ts<cutoff)].copy()
assert len(train)==model['train_events'] and train.exit_ts.max()<cutoff
assert model['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert model['source_label_sha256']==hashlib.sha256((HERE/'2024独立机会净收益标签.parquet').read_bytes()).hexdigest()
raw=train[FEATURES].to_numpy(float);mean=raw.mean(axis=0);scale=raw.std(axis=0);scale[scale<1e-12]=1.
assert np.allclose(mean,model['mean']) and np.allclose(scale,model['scale'])
X=np.column_stack([np.ones(len(raw)),np.clip((raw-mean)/scale,-5,5)])
y=train.net_win.to_numpy(float);ret=train.net_pct_notional.to_numpy(float)
def objective(b):
    z=X@b;loss=np.mean(np.logaddexp(0,z)-y*z)+.01*np.dot(b[1:],b[1:])
    grad=X.T@(expit(z)-y)/len(y);grad[1:]+=.02*b[1:];return loss,grad
res=minimize(objective,np.zeros(X.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12})
assert res.success and np.allclose(res.x,model['logistic_coefficients'],rtol=1e-9,atol=1e-10)
penalty=np.diag(np.r_[0.,np.repeat(10.,len(FEATURES))]);ridge=np.linalg.solve(X.T@X+penalty,X.T@ret)
assert np.allclose(ridge,model['ridge_coefficients'],rtol=1e-9,atol=1e-10)
V=np.column_stack([np.ones(len(pred)),np.clip((pred[FEATURES].to_numpy(float)-mean)/scale,-5,5)])
p=expit(V@res.x);r=V@ridge
assert np.allclose(p,pred.predicted_net_win,rtol=1e-11) and np.allclose(r,pred.predicted_net_pct,rtol=1e-11)
assert np.array_equal((p>=.5)&(r>0),pred.model_selected.to_numpy(bool))
assert (pred.model_feature_known_ts==pred.entry_exec_ts).all() and (pred.entry_exec_ts>=pred.decision_ts+5000).all()
for row in pred.itertuples(index=False):
    fill=row.raw_entry_5s*(1+row.side*.0005)
    assert np.isclose(row.estimated_stop_fraction,row.side*(fill-row.stop_price)/fill,rtol=1e-11)
    assert np.isclose(row.log_hourly_rvol,np.log(row.rvol),rtol=1e-11) and row.side_feature==row.side
outcomes=build(2024).set_index('observation_id');r2.configure(2024)
market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
sc={'id':'audit_unit','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':1.,'leverage':20,'stop_shock':0.}
sample=labels.iloc[np.unique(np.linspace(0,len(labels)-1,min(6,len(labels)),dtype=int))]
for z in sample.itertuples(index=False):
    row=outcomes.loc[z.observation_id];t=pd.Timestamp(int(row.ts),unit='ms',tz='UTC')
    one=pd.DataFrame([row.to_dict()]).drop(columns=['large_1pct_label','large_halfpct_label','completed_body_pct'])
    sm,_,trades,_,funding=touch.engine.simulate(sc,one,t.strftime('%Y-%m-%d'),(t+pd.Timedelta(days=1)).strftime('%Y-%m-%d'),market=market,guard=guard,save=False)
    assert sm['valid_for_comparison'] and len(trades)==1
    q=trades[0];assert q['entry_ts']==z.entry_ts and q['exit_ts']==z.exit_ts and q['reason']==z.exit_reason
    assert np.isclose(q['net'],z.net_usdt,atol=1e-9) and np.isclose(100*q['net']/q['entry_notional'],z.net_pct_notional,atol=1e-9)
    assert np.isclose(sum(f['actual_charge'] for f in funding),z.funding,atol=1e-9)
idx=pred.set_index('observation_id');accounts=records=0
for path in HERE.glob('val_may_jun_2024_*_summary.json'):
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
        q=idx.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert t['entry_ts']==q.entry_exec_ts and (q.model_selected if '_net_model_' in stem else True)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(sm['slippage']+extra)),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
    accounts+=1;records+=len(ts)
out={'all_unit_labels':len(labels),'training_labels':len(train),'opportunity_labels_replayed':len(sample),
     'prediction_rows':len(pred),'accounts_checked':accounts,'trade_records_checked':records,
     'logistic_refit_matches':True,'ridge_refit_matches':True,
     'limits':'Isolated opportunity labels and repeated historical research; actual market order fills not verified.'}
flow.dump(HERE/'净收益模型独立核验.json',out)
print('NET_MODEL_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
