from common import *
from scipy.optimize import minimize
from scipy.special import expit
from datetime import datetime,timezone

def transform(frame,median,scale):
    a=frame[FEATURES].to_numpy(float);a=np.where(np.isfinite(a),a,np.array(median))
    z=np.clip((a-np.array(median))/np.array(scale),-10,10)
    return np.column_stack([np.ones(len(z)),z])
def logistic(X,y):
    def fun(w):
        z=X@w;return float(np.logaddexp(0,z).sum()-y@z+.5*np.dot(w[1:],w[1:])),X.T@(expit(z)-y)+np.r_[0,w[1:]]
    initial=np.zeros(X.shape[1]);initial[0]=np.log(y.mean()/(1-y.mean()))
    fit=minimize(fun,initial,jac=True,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12,'gtol':1e-8})
    assert fit.success,fit.message
    return fit.x,{'success':bool(fit.success),'iterations':int(fit.nit),'gradient_norm':float(np.linalg.norm(fit.jac))}
def calibrate(z,y):
    def fun(ab):
        a,b=ab;t=a*z+b;e=expit(t)-y
        return float(np.logaddexp(0,t).sum()-y@t+.5*(a-1)**2),np.array([e@z+(a-1),e.sum()])
    fit=minimize(fun,np.array([1.,0.]),jac=True,bounds=[(0,None),(None,None)],method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12,'gtol':1e-8})
    assert fit.success,fit.message
    return fit.x
def idhash(d):return hashlib.sha256('\n'.join(sorted(d.observation_id)).encode()).hexdigest()

def main():
    assert not (OUT/'models/FROZEN.json').exists(),'No performance-driven refit'
    signals=pd.read_parquet(OUT/'signals/all.parquet');lab=pd.read_parquet(OUT/'labels/development.parquet')
    merged=signals.merge(lab.drop(columns=['variant','decision_ts']),on='observation_id',how='left',validate='one_to_one')
    predictions=[];models={}
    for variant in ['B','C']:
        d=merged[merged.variant.eq(variant)&merged.features_valid&merged.label_status.eq('valid')]
        train=d[d.decision_ts.lt(TRAIN_END)&d.decision_ts.add(65*M).lt(TRAIN_END)&d.exit_ts.lt(TRAIN_END)].copy()
        cal=d[d.decision_ts.ge(TRAIN_END)&d.decision_ts.lt(CAL_END)&d.decision_ts.add(65*M).lt(CAL_END)&d.exit_ts.lt(CAL_END)].copy()
        assert len(train)>=200 and train.y.value_counts().min()>=30
        assert len(cal)>=100 and cal.y.value_counts().min()>=20
        median=train[FEATURES].median().fillna(0).to_numpy();scale=(train[FEATURES].quantile(.75)-train[FEATURES].quantile(.25)).fillna(1).to_numpy(copy=True);scale[scale==0]=1
        X=transform(train,median,scale);w,fitinfo=logistic(X,train.y.to_numpy(float));cz=transform(cal,median,scale)@w;ab=calibrate(cz,cal.y.to_numpy(float))
        W=float(cal.loc[cal.y.eq(1),'net_R'].mean());L=float(-cal.loc[cal.y.eq(0),'net_R'].mean())
        cp=expit(ab[0]*cz+ab[1])
        model={'variant':variant,'features':FEATURES,'median':median.tolist(),'scale':scale.tolist(),'weights':w.tolist(),'calibration':ab.tolist(),'calibration_mean_win_net_R':W,'calibration_mean_loss_net_R':L,
         'training_samples':len(train),'calibration_samples':len(cal),'training_days':int((train.decision_ts//D).nunique()),'calibration_days':int((cal.decision_ts//D).nunique()),
         'training_win_rate':float(train.y.mean()),'calibration_win_rate':float(cal.y.mean()),'calibration_brier':float(np.mean((cp-cal.y.to_numpy())**2)),
         'training_max_label_ts':int(train.exit_ts.max()),'calibration_max_label_ts':int(cal.exit_ts.max()),'train_ids_sha256':idhash(train),'calibration_ids_sha256':idhash(cal),
         'fit':fitinfo,'protocol_sha256':sha(OUT/'protocol.json'),'no_grid_or_refit':True}
        dump(OUT/'models'/f'{variant}.json',model);models[variant]=model
        save(f'models/{variant}-train_ids.parquet',train[['observation_id','decision_ts','exit_ts','y','net_R']]);save(f'models/{variant}-calibration_ids.parquet',cal[['observation_id','decision_ts','exit_ts','y','net_R']])
        allrows=signals[signals.variant.eq(variant)].copy();allrows['raw_probability']=np.nan;allrows['probability']=np.nan;allrows['estimated_net_R']=np.nan
        mask=allrows.features_valid;az=transform(allrows.loc[mask],median,scale)@w;prob=expit(ab[0]*az+ab[1]);allrows.loc[mask,'raw_probability']=expit(az);allrows.loc[mask,'probability']=prob;allrows.loc[mask,'estimated_net_R']=prob*W-(1-prob)*L
        allrows['filter_pass']=allrows.features_valid&allrows.probability.ge(.65)&allrows.estimated_net_R.gt(0)
        allrows['split']=np.select([allrows.decision_ts.lt(TRAIN_END),allrows.decision_ts.lt(CAL_END)],['train','calibration'],'evaluation')
        predictions.append(allrows)
        print('FIT',variant,'ntrain',len(train),'ncal',len(cal),'Platt',ab.tolist(),flush=True)
    pred=pd.concat(predictions,ignore_index=True);save('predictions/all.parquet',pred)
    files={f'{v}.json':sha(OUT/'models'/f'{v}.json') for v in ['B','C']}
    dump(OUT/'models/FROZEN.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'models':files,'prediction_sha256':sha(OUT/'predictions/all.parquet'),'evaluation_outcomes_read_in_fit':False,'protocol_sha256':sha(OUT/'protocol.json')})
    print('MODELS_FROZEN',flush=True)

if __name__=='__main__':main()
