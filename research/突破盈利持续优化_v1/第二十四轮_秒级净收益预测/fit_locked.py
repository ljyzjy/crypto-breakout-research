"""Freeze a cost-aware net-win and expected-net model before May 2024 validation."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from build_labels import FEATURES
HERE=Path(__file__).resolve().parent
d=pd.read_parquet(HERE/'2024独立机会净收益标签.parquet')
cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
train=d[(d.entry_ts<cutoff)&(d.exit_ts<cutoff)].copy()
assert len(train)>=60 and train.observation_id.is_unique and set(train.net_win.unique())=={0,1}
raw=train[FEATURES].to_numpy(float);y=train.net_win.to_numpy(float);returns=train.net_pct_notional.to_numpy(float)
assert np.isfinite(raw).all() and np.isfinite(returns).all()
mean=raw.mean(axis=0);scale=raw.std(axis=0);scale[scale<1e-12]=1.
x=np.clip((raw-mean)/scale,-5,5);X=np.column_stack([np.ones(len(x)),x])
def objective(beta):
    z=X@beta;loss=np.mean(np.logaddexp(0,z)-y*z)+.01*np.dot(beta[1:],beta[1:])
    grad=X.T@(expit(z)-y)/len(y);grad[1:]+=.02*beta[1:];return loss,grad
fit=minimize(objective,np.zeros(X.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12})
if not fit.success:raise RuntimeError('optimizer_failure:'+fit.message)
penalty=np.diag(np.r_[0.,np.repeat(10.,x.shape[1])]);ridge=np.linalg.solve(X.T@X+penalty,X.T@returns)
model={'features':FEATURES,'mean':mean.tolist(),'scale':scale.tolist(),'logistic_coefficients':fit.x.tolist(),
       'ridge_coefficients':ridge.tolist(),'train_events':len(train),'train_wins':int(y.sum()),
       'last_train_exit_ts':int(train.exit_ts.max()),'cutoff_ts':cutoff,'logistic_l2':.01,'ridge_l2':10.,
       'minimum_predicted_win':.5,'minimum_predicted_net_pct':0.,
       'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
       'source_label_sha256':hashlib.sha256((HERE/'2024独立机会净收益标签.parquet').read_bytes()).hexdigest(),
       'note':'Uncalibrated probability and notional PnL estimate; account backtest and unseen evaluation are separate.'}
(HERE/'四月底固定净收益模型.json').write_text(json.dumps(model,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print('NET_MODEL_FROZEN',json.dumps({'train_events':len(train),'train_wins':int(y.sum()),'last_train_exit_ts':model['last_train_exit_ts']},ensure_ascii=False),flush=True)
