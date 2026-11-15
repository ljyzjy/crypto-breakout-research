"""Independent numeric reconstruction of frozen screening; no candidate search."""
from pathlib import Path
import json, hashlib, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent
P3=ROOT.parent; INC=P3/'incremental'; P2=P3.parent/'feature-research-phase2'
M=60_000; DAY=86_400_000
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def id_hash(values):return hashlib.sha256('\n'.join(sorted(map(str,values))).encode()).hexdigest()
def time(s):return int(pd.Timestamp(s,tz='UTC').timestamp()*1000)
TR=time('2025-01-01'); SC=time('2025-04-01'); EV=time('2025-07-01')

def reconstruct_design(d,model):
    q=d.copy()
    q['signed_r6']=q.side*q.r6; q['signed_btc_r6']=q.side*q.btc_r6
    q['signed_residual6']=q.side*q.residual6
    q['log_quote_rvol']=np.log1p(q.quote_rvol); q['log_count_rvol']=np.log1p(q.count_rvol)
    cols=[np.ones(len(q))]
    for name in model['input_columns']:
        v=q[name].to_numpy(float); sc=model['scaler'][name]
        np.testing.assert_allclose(np.median(v),sc['median'],rtol=1e-12,atol=1e-12)
        iq=np.percentile(v,75)-np.percentile(v,25)
        np.testing.assert_allclose(iq,sc['iqr'],rtol=1e-12,atol=1e-12)
    for name in model['active_columns']:
        sc=model['scaler'][name]; cols.append((q[name].to_numpy(float)-sc['median'])/sc['scale'])
    assert model['coin_levels']==sorted(q.symbol.astype(str).unique())
    cols.extend((q.symbol.astype(str).to_numpy()==coin).astype(float) for coin in model['coin_levels'][1:])
    return np.column_stack(cols)

def main():
    proto=read(P3/'protocol.json'); freeze=read(P3/'registration_freeze.json')
    assert sha(P3/'protocol.json')==freeze['protocol_sha256']
    for p,h in read(INC/'component_freeze.json')['source_hashes'].items():assert sha(Path(p))==h
    ready=read(INC/'RESULTS_READY.json')
    assert sha(INC/'incremental_results.json')==ready['summary_sha256']
    assert sha(INC/'selection.json')==ready['selection_sha256']
    result=read(INC/'incremental_results.json'); selected=read(INC/'selection.json')
    cohort_cache={}; labels_cache={}; groups=[]; rawps={}
    for res in result['groups']:
        group=res['group']; cohort=res['cohort']
        if cohort not in cohort_cache:
            frames=[]
            for p in sorted((P2/'feature_outputs'/cohort).glob('*.parquet')):
                d=pd.read_parquet(p,filters=[('decision_ts','<',EV)])
                d['observation_id']=d.event_id.astype(str) if cohort=='events' else d.symbol.astype(str)+'|'+d.decision_ts.astype(str)
                frames.append(d)
            cohort_cache[cohort]=pd.concat(frames,ignore_index=True)
            labels_cache[cohort]=pd.read_parquet(INC/'labels'/f'{cohort}-train_screen.parquet')
        source=cohort_cache[cohort]; labels=labels_cache[cohort]
        oldmask=pd.read_parquet(P2/'matched_samples'/f'{group}-mask.parquet')[['observation_id','included']].rename(columns={'included':'phase2_include'})
        group_ids={}
        for split,lo,hi in [('train',TR,SC),('screen',SC,EV)]:
            saved=pd.read_parquet(INC/'matched'/f'{group}-{split}.parquet')
            f=source.loc[source.decision_ts.ge(lo)&source.decision_ts.lt(hi),['observation_id','decision_ts']].merge(oldmask,on='observation_id',validate='one_to_one')
            f=f.merge(labels[['observation_id','label_valid_30','entry_ts','exit_ts_30','exit_ts_60']],on='observation_id',validate='one_to_one')
            independent=f.phase2_include & (f.decision_ts<hi-65*M)&(f.exit_ts_60<hi)&f.label_valid_30
            expected=set(f.loc[independent,'observation_id'])
            assert expected==set(saved.loc[saved.included,'observation_id'])
            assert set(saved.observation_id)==set(f.observation_id)
            assert len(saved)==len(f)
            assert ((f.loc[independent,'entry_ts']-f.loc[independent,'decision_ts'])==M).all()
            group_ids[split]=expected
        model=read(INC/'models'/f'{group}-train.json')
        train=source.loc[source.observation_id.isin(group_ids['train'])].merge(labels[['observation_id',model['target'],'exit_ts_60']],on='observation_id')
        for kind in ['baseline','enhanced']:
            xmodel=model[kind]; md=xmodel['metadata']
            assert xmodel['n_rows']==len(train) and md['fit_ids_sha256']==id_hash(train.observation_id)
            assert md['fit_decision_max']==int(train.decision_ts.max())<SC-65*M
            assert md['fit_label60_max']==int(train.exit_ts_60.max())<SC
            assert md['fit_feature_known_max']<=md['fit_decision_max']
            x=reconstruct_design(train,xmodel)
            beta,_,rank,_=np.linalg.lstsq(x,train[model['target']].to_numpy(),rcond=1e-12)
            np.testing.assert_allclose(beta,xmodel['coef'],rtol=1e-6,atol=2e-7)
            assert int(rank)==xmodel['rank']
        p=pd.read_parquet(INC/'screen_predictions'/f'{group}.parquet')
        assert set(p.observation_id)==group_ids['screen']
        assert (p.fit_label_end<p.decision_ts).all()
        assert p.exit_ts_30.lt(EV).all()
        target=model['target']
        q=p.merge(labels[['observation_id',target]].rename(columns={target:'source_target'}),on='observation_id')
        np.testing.assert_allclose(q[target],q.source_target,rtol=0,atol=0)
        q['utc_day']=q.decision_ts//DAY
        q['lb']=(q[target]-q.baseline_prediction)**2
        q['le']=(q[target]-q.enhanced_prediction)**2
        daily=q.groupby(['utc_day','symbol'])[['lb','le']].mean().groupby('utc_day').mean().reindex(np.arange(SC//DAY,EV//DAY))
        a=(daily['lb']-daily['le']).to_numpy(); mean=float(np.nanmean(a))
        rng=np.random.default_rng(20261113); null=[]; draws=[]
        for _ in range(2000):
            starts=rng.integers(0,len(a)-6,size=(len(a)+6)//7)
            idx=np.concatenate([np.arange(t,t+7) for t in starts])[:len(a)]
            draws.append(float(np.nanmean(a[idx])))
            null.append(float(np.nanmean((a-mean)[idx])))
        pv=(1+sum(x>=mean for x in null))/2001
        ci=np.percentile(draws,[2.5,97.5])
        np.testing.assert_allclose(mean,res['mean_difference'],rtol=1e-11,atol=1e-10)
        np.testing.assert_allclose(pv,res['p_raw'],rtol=0,atol=0)
        np.testing.assert_allclose(ci,res['ci95'],rtol=1e-11,atol=1e-9)
        rawps[group]=pv
        groups.append({'group':group,'train_rows':len(train),'screen_rows':len(p),'mse_difference':mean,
            'relative_loss_improvement':mean/float(daily.lb.mean()),'p_raw':pv,'ci95':ci.tolist(),
            'paired_mask_rebuilt':True,'training_scales_FE_coefficients_rebuilt':True,
            'strict_model_and_label_timestamps':True})
    order=sorted(rawps,key=lambda k:(rawps[k],k)); adj={}; prev=0
    for i,g in enumerate(order):prev=max(prev,min(1,rawps[g]*(6-i)));adj[g]=prev
    for g in groups:g['p_holm6']=adj[g['group']]
    independent_selected=[g['group'] for g in groups if g['mse_difference']>0 and g['p_holm6']<=.05]
    assert independent_selected==selected['selected_groups']==result['selected_groups']
    assert independent_selected==[]
    pred=pd.read_parquet(INC/'predictions/account_events.parquet')
    assert not any(('label' in c and not c.endswith('_fit_label_end')) or c.startswith('gross_bp') for c in pred.columns)
    assert pred.decision_ts.ge(EV).all() and pred.feature_known_ts.le(pred.decision_ts).all()
    assert not list((INC/'models').glob('*refit*'))
    # Small independent actual-label oracle: stream eight coins, both cohorts, up to three rows per sign.
    sys.path.insert(0,str(P3/'account'));import market_io
    sampled=0; maximum_error=0.
    for cohort,lab in labels_cache.items():
        contracts=sorted(lab.contract.dropna().unique())
        chosen=[x for x in ['BTCUSDT','ETHUSDT','1000PEPEUSDT','AAVEUSDT','AXSUSDT','RUNEUSDT','SOLUSDT','TRUMPUSDT'] if x in contracts]
        for contract in chosen:
            cand=lab.loc[lab.contract.eq(contract)&lab.label_valid_60]
            if cand.empty:continue
            rows=[]
            for side in [-1,1]:
                s=cand.loc[cand.side.eq(side)]
                if len(s):rows.extend(s.iloc[np.unique(np.linspace(0,len(s)-1,min(3,len(s)),dtype=int))].to_dict('records'))
            for r in rows:
                raw=market_io.load_minutes(contract,int(r['entry_ts']),int(r['exit_ts_60'])+M).set_index('ts')
                ep=float(raw.loc[r['entry_ts'],'open']);sgn=r['side']
                for h in [15,30,60]:
                    xt=int(r[f'exit_ts_{h}']);xp=float(raw.loc[xt,'open']);held=raw.loc[(raw.index>=r['entry_ts'])&(raw.index<xt)]
                    assert len(held)==h
                    hh=float(held.high.max());ll=float(held.low.min())
                    vals={'gross_bp':sgn*np.log(xp/ep)*10000,
                        'mae_bp':max(0.,np.log(ep/ll) if sgn==1 else np.log(hh/ep))*10000,
                        'mfe_bp':max(0.,np.log(hh/ep) if sgn==1 else np.log(ep/ll))*10000}
                    for k,v in vals.items():
                        err=abs(v-r[f'{k}_{h}']); maximum_error=max(maximum_error,err)
                        assert err<1e-8
                sampled+=1
    audit={'completed_utc':datetime.now(timezone.utc).isoformat(),'all_checks_passed':True,
        'protocol_sha256':sha(P3/'protocol.json'),'groups':groups,'selected_groups':independent_selected,
        'actual_label_samples':sampled,'actual_label_max_abs_error_bp':maximum_error,
        'account_predictions_contain_no_forward_outcomes':True,'no_unjustified_refit_or_candidate_created':True,
        'scope':'Exact independent six-group masks, train coefficients/scalers/FE, screen loss/bootstrap/Holm; finite actual-label samples; historical exploratory inference only.'}
    (ROOT/'incremental_independent.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit))

if __name__=='__main__':main()
