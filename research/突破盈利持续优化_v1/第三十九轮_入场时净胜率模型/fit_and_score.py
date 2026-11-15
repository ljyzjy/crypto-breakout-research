"""Fit a fixed regularized win classifier and freeze decisions before validation PnL."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
H=Path(__file__).resolve().parent;I=H/'冻结输入'
FEATURES=['directional_prior_body_atr','log1p_prior_trade_pace','atr_fraction_p5','cross_phase',
          'directional_p5_move_atr','p5_flow_imbalance','log1p_p5_notional','log1p_hour_rvol','liquidity_rank']
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def vector(e):
    side=int(e['side']);atr=float(e['atr']);ref=float(e['raw_entry_5s']);cross=float(e['signal_close'])
    before=float(e['prior_prefix_ratio']);buy=float(e['buy_notional']);sell=float(e['sell_notional']);rvol=float(e['rvol'])
    t=int(e['decision_ts']);p5=int(e['entry_exec_ts']);start=int(e['quarter_start']);end=int(e['quarter_end'])
    if side not in (-1,1) or atr<=0 or ref<=0 or cross<=0 or min(before,buy,sell,rvol)<0:raise ValueError('bad_feature_values')
    if not (start<=t<end and t+5000<=p5<end):raise ValueError('feature_time')
    a=np.asarray([side*float(e['prior_body_atr']),np.log1p(before),atr/ref,(t-start)/900_000,
      side*(ref-cross)/atr,float(e['five_imbalance']),np.log1p(buy+sell),np.log1p(rvol),float(e['liquidity_rank'])],float)
    if not np.isfinite(a).all():raise ValueError('nonfinite_feature')
    return a
def evaluate(probabilities,mu,scale,coeff):
    x=np.clip((probabilities-mu)/scale,-5,5);return expit(coeff[0]+x@coeff[1:])
def fit(x,y):
    mu=x.mean(axis=0);scale=x.std(axis=0);scale=np.where(scale>0,scale,1.);v=np.clip((x-mu)/scale,-5,5)
    def obj(b):
        z=b[0]+v@b[1:];p=expit(z);loss=np.mean(np.logaddexp(0,z)-y*z)+.1*np.dot(b[1:],b[1:])
        grad=np.r_[np.mean(p-y),v.T@(p-y)/len(y)+.2*b[1:]]
        return float(loss),grad
    initial=np.zeros(v.shape[1]+1);initial[0]=np.log(y.mean()/(1-y.mean()))
    r=minimize(obj,initial,jac=True,method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12,'gtol':1e-8})
    if not r.success or not np.isfinite(r.x).all():raise ValueError('optimizer_failed:'+str(r.message))
    return mu,scale,r.x,{'iterations':int(r.nit),'loss':float(r.fun),'message':str(r.message)}
def decisions(sig,models):
    lo=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000);hi=int(pd.Timestamp('2024-06-30',tz='UTC').timestamp()*1000)
    rows=[]
    for e in sig.to_dict('records'):
        if e['source_year']=='2024' and lo<=int(e['trigger_minute'])<hi:period='2024_may_jun'
        elif e['source_year']=='2026':period='2026_may_jul'
        else:continue
        for lev in (10,20):
            status=e['status'];pre=e.get(f'precheck_{lev}x');prob=None
            if status not in BENIGN:decision='source_unknown'
            elif status!='qualified':decision='known_no_order'
            elif pd.isna(pre):decision='precheck_unknown'
            elif pre!='passed':decision='known_no_order'
            else:
                try:
                    v=vector(e);m=models[str(lev)];prob=float(evaluate(v,np.array(m['mean']),np.array(m['scale']),np.array(m['coefficients'])))
                    decision='selected' if prob>=.60 else 'model_rejected'
                except (ValueError,TypeError,KeyError,OverflowError):decision='feature_unknown'
            rows.append({'observation_id':e['observation_id'],'period':period,'leverage':lev,
                         'decision':decision,'model_probability':prob,'source_status':status})
    out=pd.DataFrame(rows);assert not out.duplicated(['observation_id','leverage']).any()
    return out.sort_values(['period','observation_id','leverage']).reset_index(drop=True)
def main():
    snap=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()==snap['plan_sha256']
    for name,x in snap['inputs'].items():assert hashlib.sha256((I/name).read_bytes()).hexdigest()==x['sha256']
    signal=pd.read_parquet(I/'train_signal.parquet').set_index('observation_id');ledger=pd.read_parquet(I/'train_ledger.parquet')
    models={};cut=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    for lev in (10,20):
        valid=ledger[ledger.variant.eq(f'normal_2r_{lev}x')&ledger.status.eq('verified')&ledger.risk_status.eq('verified')&~ledger.liq_proxy.fillna(False)]
        X=[];y=[];bad=[]
        for r in valid.itertuples(index=False):
            e=signal.loc[r.observation_id].to_dict();assert e['status']=='qualified' and e[f'precheck_{lev}x']=='passed'
            assert int(e['quarter_end'])+60_000<=cut and int(r.exit_ts)<=int(e['quarter_end'])+60_000
            try:X.append(vector(e));y.append(int(float(r.net_per_unit_notional)>0))
            except (ValueError,TypeError,KeyError,OverflowError):bad.append(r.observation_id)
        X=np.asarray(X,float);y=np.asarray(y,float)
        if len(X)<100 or not (0<y.sum()<len(y)):raise ValueError('training_sample_insufficient')
        mean,scale,coef,opt=fit(X,y)
        models[str(lev)]={'features':FEATURES,'mean':mean.tolist(),'scale':scale.tolist(),'coefficients':coef.tolist(),
          'regularization':.1,'threshold':.60,'train_events':len(y),'train_wins':int(y.sum()),
          'invalid_training_feature_ids':bad,'optimizer':opt}
    artifact={'models':models,'training_cutoff':'2024-05-01 00:00 UTC','plan_sha256':snap['plan_sha256'],
              'note':'Training labels are realized after exit; validation decisions use only P5 known fields. Probabilities are not calibrated.'}
    (H/'四月底固定模型.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
    # Deliberately do not open all_paths.parquet, a file containing subsequent execution outcomes.
    all_signal=pd.read_parquet(I/'all_signal.parquet');score=decisions(all_signal,models)
    score.to_parquet(H/'事前固定预测.parquet',index=False)
    counts=score.groupby(['period','leverage','decision'],dropna=False).size().reset_index(name='count').to_dict('records')
    summary={'training':{k:{'events':v['train_events'],'wins':v['train_wins'],'invalid_feature_count':len(v['invalid_training_feature_ids'])} for k,v in models.items()},
             'validation_decision_counts':counts,'model_sha256':hashlib.sha256((H/'四月底固定模型.json').read_bytes()).hexdigest(),
             'score_sha256':hashlib.sha256((H/'事前固定预测.parquet').read_bytes()).hexdigest(),
             'note':'The score file was produced without reading validation path/exit/return data. No PnL is calculated here.'}
    (H/'事前预测质量.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('NETMODEL39_SCORES_FROZEN',json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
