"""Fit and freeze a regularized candle-label model using 2024 only."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from features import build,FEATURES
HERE=Path(__file__).resolve().parent
d=build(2024)
cutoff=int(pd.Timestamp('2024-07-01',tz='UTC').timestamp()*1000)
d=d[d.quarter_end.le(cutoff)].copy()
assert len(d)>=100 and d.observation_id.is_unique
raw=d[FEATURES].to_numpy(float);y=d.large_1pct_label.astype(bool).to_numpy(float)
assert set(np.unique(y))=={0.,1.} and np.isfinite(raw).all()
mean=raw.mean(axis=0);scale=raw.std(axis=0);scale[scale<1e-12]=1.
x=np.clip((raw-mean)/scale,-5,5);design=np.column_stack([np.ones(len(x)),x])
def objective(beta):
    z=design@beta;value=np.mean(np.logaddexp(0,z)-y*z)+.1*np.dot(beta[1:],beta[1:])
    grad=design.T@(expit(z)-y)/len(y);grad[1:]+=.2*beta[1:]
    return value,grad
fit=minimize(objective,np.zeros(design.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12})
if not fit.success:raise RuntimeError('model_fit_failed:'+fit.message)
train=HERE/'训练特征与事后大柱标签.parquet';d.to_parquet(train,index=False)
model={'features':FEATURES,'mean':mean.tolist(),'scale':scale.tolist(),'coefficients':fit.x.tolist(),
       'training_events':len(d),'training_large_events':int(y.sum()),'cutoff_utc_ms':cutoff,
       'threshold':.30,'l2_penalty':.10,'training_objective':float(fit.fun),
       'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
       'training_sha256':hashlib.sha256(train.read_bytes()).hexdigest(),
       'note':'Large-bar class is ex post and trained only before evaluation; probabilities not calibrated.'}
(HERE/'固定大柱预判模型.json').write_text(json.dumps(model,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print('BIGBAR_MODEL_FROZEN',json.dumps({'training_events':len(d),'training_large_events':int(y.sum()),
      'threshold':.30,'plan_sha256':model['plan_sha256']},ensure_ascii=False),flush=True)
