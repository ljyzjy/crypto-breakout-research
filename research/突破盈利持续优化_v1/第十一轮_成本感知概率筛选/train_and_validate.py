"""Fixed regularized prediction models; chronological training and account replay."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
R2=PARENT/'第二轮_成本空间与即时成交';R8=PARENT/'第八轮_BTC短时领先';R9=PARENT/'第九轮_突破后延长持仓'
for p in (PARENT,R2,R8,R9,HERE):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_extended as extended
from build_training_labels import FEATURES,build_features

def fit(frame):
    raw=frame[FEATURES].to_numpy(float);y=frame.target.to_numpy(float);returns=frame.net_pct_notional.to_numpy(float)
    assert len(raw)>=100 and np.isfinite(raw).all() and set(np.unique(y))=={0.,1.}
    mean=raw.mean(axis=0);scale=raw.std(axis=0);scale[scale<1e-12]=1.
    x=np.clip((raw-mean)/scale,-5,5);design=np.column_stack([np.ones(len(x)),x])
    def objective(beta):
        z=design@beta
        value=np.mean(np.logaddexp(0,z)-y*z)+.1*np.dot(beta[1:],beta[1:])
        error=expit(z)-y;grad=design.T@error/len(y);grad[1:]+=.2*beta[1:]
        return value,grad
    result=minimize(objective,np.zeros(design.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12})
    if not result.success:raise RuntimeError('logistic_optimization_failed:'+str(result.message))
    penalty=np.diag(np.r_[0.,np.repeat(10.,x.shape[1])])
    ridge=np.linalg.solve(design.T@design+penalty,design.T@returns)
    return {'features':FEATURES,'mean':mean.tolist(),'scale':scale.tolist(),
            'logistic_coefficients':result.x.tolist(),'ridge_coefficients':ridge.tolist(),
            'training_count':len(y),'training_wins':int(y.sum()),'logistic_objective':float(result.fun)}
def predict(data,model):
    data=build_features(data);raw=data[FEATURES].to_numpy(float)
    valid=np.isfinite(raw).all(axis=1);prob=np.full(len(data),np.nan);expected=np.full(len(data),np.nan)
    x=np.clip((raw[valid]-np.array(model['mean']))/np.array(model['scale']),-5,5)
    design=np.column_stack([np.ones(len(x)),x])
    prob[valid]=expit(design@np.array(model['logistic_coefficients']))
    expected[valid]=design@np.array(model['ridge_coefficients'])
    data['predicted_net_win_probability']=prob;data['predicted_net_pct_notional']=expected
    data['model_selected']=valid&(prob>=.60)&(expected>0)
    return data
def main():
    labels=pd.read_parquet(HERE/'训练期已完成单笔标签.parquet')
    cutoff=int(pd.Timestamp('2024-07-01',tz='UTC').timestamp()*1000)
    assert (labels.exit_ts<cutoff).all() and labels.observation_id.is_unique
    model=fit(labels)
    model.update(plan_sha256=hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
                 training_sha256=hashlib.sha256((HERE/'训练期已完成单笔标签.parquet').read_bytes()).hexdigest(),
                 threshold_probability=.60,threshold_predicted_net_pct=0.,
                 notes='L2 models; predictions are not calibrated probabilities and are not evidence of actual fills.')
    flow.dump(HERE/'固定预测模型.json',model)
    print('COST_AWARE_MODEL_FROZEN','n',model['training_count'],'wins',model['training_wins'],flush=True)
    frozen_hash=hashlib.sha256((HERE/'固定预测模型.json').read_bytes()).hexdigest()
    flow.HERE=HERE;flow.eng=extended.engine;flow.candidate=lambda signals,name:signals[signals.model_selected].copy()
    results=[];prediction_meta=[]
    period_groups=[(2024,[('h2_2024','2024-07-01','2024-12-31')]),
                   (2026,[('full_2026','2026-05-01','2026-10-31'),('may_jul_2026','2026-05-01','2026-07-31'),
                          ('aug_oct_2026','2026-08-01','2026-10-31'),('nov12_2026','2026-11-01','2026-11-12')])]
    for year,periods in period_groups:
        r2.configure(year)
        sources=[R8/f'{year}触价前市场特征_later.parquet']
        if year==2026:sources.insert(0,R8/'2026触价前市场特征.parquet')
        data=pd.concat([pd.read_parquet(p) for p in sources],ignore_index=True)
        assert data.observation_id.is_unique
        if year==2024:
            embargo=int(pd.Timestamp('2024-07-01 04:00',tz='UTC').timestamp()*1000)
            data=data[data.decision_ts.ge(embargo)].copy()
        data=predict(data,model)
        data[['observation_id','decision_ts','predicted_net_win_probability','predicted_net_pct_notional','model_selected']].to_parquet(HERE/f'{year}冻结模型预测.parquet',index=False)
        prediction_meta.append({'year':year,'events':len(data),'valid_feature_events':int(data.predicted_net_win_probability.notna().sum()),
                                'selected_events':int(data.model_selected.sum())})
        market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        for period,start,end in periods:
          for leverage in (10,20):
           for scenario in ('main','stress'):
            results.append(flow.simulate(data,'cost_model_1r',start,end,market,guard,leverage,scenario,period,
                                        target_override=1.,max_hold_minutes=240,allow_overnight=True))
    assert hashlib.sha256((HERE/'固定预测模型.json').read_bytes()).hexdigest()==frozen_hash
    flow.dump(HERE/'模型预测数量.json',prediction_meta)
    flow.dump(HERE/'冻结模型后续账户对照.json',results)
    pd.DataFrame(results).to_csv(HERE/'冻结模型后续账户对照.csv',index=False,encoding='utf-8-sig')
    print('COST_AWARE_MODEL_EVALUATED',len(results),'valid',sum(x['valid_for_comparison'] for x in results),
          'prediction_counts',json.dumps(prediction_meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
