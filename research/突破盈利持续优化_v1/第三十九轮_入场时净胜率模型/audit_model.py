"""Independently audit frozen model arithmetic and future-field invariance."""
import json,math
from pathlib import Path
import numpy as np,pandas as pd
from scipy.special import expit
import fit_and_score as m
H=Path(__file__).resolve().parent;I=H/'冻结输入'

def main():
    artifact=json.loads((H/'四月底固定模型.json').read_text(encoding='utf-8'));models=artifact['models']
    sig=pd.read_parquet(I/'train_signal.parquet').set_index('observation_id');ledger=pd.read_parquet(I/'train_ledger.parquet')
    hold=pd.read_parquet(I/'all_signal.parquet');before=m.decisions(hold,models)
    altered=hold.copy()
    # These synthetic future values are not part of the source schema and must
    # not affect predictions; path archives are never read by decisions().
    altered['exit_ts']=9_999_999_999_999;altered['exit_price']=10**12;altered['exit_reason']='perturbed_future'
    altered['net_per_unit_notional']=-999.;altered['future_bar_close']=10**12
    after=m.decisions(altered,models);pd.testing.assert_frame_equal(before,after,check_dtype=True)
    recorded=pd.read_parquet(H/'事前固定预测.parquet');pd.testing.assert_frame_equal(before,recorded,check_dtype=True)
    checks=[]
    for lev in (10,20):
        model=models[str(lev)];X=[];Y=[];bad=set(model['invalid_training_feature_ids'])
        for r in ledger.itertuples(index=False):
            if r.variant!=f'normal_2r_{lev}x' or r.status!='verified' or r.risk_status!='verified' or r.liq_proxy or r.observation_id in bad:continue
            e=sig.loc[r.observation_id];assert e.status=='qualified' and e[f'precheck_{lev}x']=='passed'
            assert int(e.quarter_end)+60000<=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
            # Reconstruct features without calling the model's vector function.
            side=int(e.side);a=float(e.atr);p=float(e.raw_entry_5s);trigger=float(e.signal_close)
            x=[side*float(e.prior_body_atr),math.log1p(float(e.prior_prefix_ratio)),a/p,
               (int(e.decision_ts)-int(e.quarter_start))/900000,side*(p-trigger)/a,float(e.five_imbalance),
               math.log1p(float(e.buy_notional)+float(e.sell_notional)),math.log1p(float(e.rvol)),float(e.liquidity_rank)]
            assert int(e.entry_exec_ts)>=int(e.decision_ts)+5000 and all(math.isfinite(z) for z in x)
            X.append(x);Y.append(int(r.net_per_unit_notional>0))
        x=np.asarray(X);y=np.asarray(Y);mu=x.mean(0);sd=x.std(0);sd=np.where(sd>0,sd,1.)
        assert np.allclose(mu,model['mean'],rtol=1e-12,atol=1e-12) and np.allclose(sd,model['scale'],rtol=1e-12,atol=1e-12)
        assert len(y)==model['train_events'] and int(y.sum())==model['train_wins']
        x=np.clip((x-mu)/sd,-5,5);coef=np.asarray(model['coefficients']);p=expit(coef[0]+x@coef[1:])
        grad=np.r_[np.mean(p-y),x.T@(p-y)/len(y)+.2*coef[1:]];g=float(np.max(np.abs(grad)))
        assert g<1e-5
        checks.append({'leverage':lev,'training_events':len(y),'training_wins':int(y.sum()),'maximum_abs_gradient':g})
    counts=[]
    for (period,lev),g in before.groupby(['period','leverage']):
        p=g.model_probability.dropna()
        counts.append({'period':period,'leverage':int(lev),'scored':len(p),'selected':int(g.decision.eq('selected').sum()),
                       'source_unknown':int(g.decision.eq('source_unknown').sum()),'max_probability':float(p.max()) if len(p) else None})
    result={'training_checks':checks,'validation_counts':counts,'synthetic_future_fields_perturbed':True,
            'predictions_unchanged':True,'validation_paths_not_loaded_by_predictor':True,'all_checks_pass':True,
            'note':'Arithmetic and dependency checks do not validate calibration or overcome historical selection bias.'}
    (H/'模型独立及时序核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('NETMODEL39_AUDIT',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
