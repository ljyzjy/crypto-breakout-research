"""Explicitly authorized run only, after parent protocol is frozen.

Usage: python run_incremental.py --frozen-protocol-sha256 SHA
No real outcome is read when imported. Last 300-day outcomes are never loaded here.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from methods import *

HERE=Path(__file__).resolve().parent
PHASE3=HERE.parent
PHASE2=PHASE3.parent/'feature-research-phase2'
TRAIN_START=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
TRAIN_END=int(pd.Timestamp('2025-04-01',tz='UTC').timestamp()*1000)
SCREEN_END=int(pd.Timestamp('2025-07-01',tz='UTC').timestamp()*1000)
EVAL_END=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)

def save_json(path,value):
    path.parent.mkdir(exist_ok=True,parents=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def save_parquet(path,frame):
    path.parent.mkdir(exist_ok=True,parents=True);frame.to_parquet(path,index=False)

def load_cohort(cohort):
    files=sorted((PHASE2/'feature_outputs'/cohort).glob('*.parquet'))
    d=pd.concat([pd.read_parquet(p) for p in files],ignore_index=True)
    d['observation_id']=d.event_id.astype(str) if cohort=='events' else d.symbol.astype(str)+'|'+d.decision_ts.astype(str)
    if d.observation_id.duplicated().any():raise ValueError('Duplicate cohort IDs: '+cohort)
    if (d.feature_known_ts>d.decision_ts).any():raise ValueError('Future-known feature')
    return d.sort_values(['decision_ts','symbol','observation_id']).reset_index(drop=True)

def build_training_labels(cohort,d,market):
    # Never requests final-evaluation outcomes. Purged split boundaries are applied later.
    opportunities=d.loc[d.decision_ts.ge(TRAIN_START)&d.decision_ts.lt(SCREEN_END)]
    out=[]
    for contract,part in opportunities.groupby('contract',dropna=False,observed=True):
        if pd.isna(contract):m=pd.DataFrame()
        else:
            start=int(part.decision_ts.min())+MINUTE
            # Clamp at frozen training/selection end: labels beyond it become unavailable.
            end=min(int(part.decision_ts.max())+62*MINUTE,SCREEN_END)
            m=market.load_minutes(str(contract),start,end)
        out.append(make_labels(part,m))
    labels=pd.concat(out,ignore_index=True).sort_values('observation_id')
    if len(labels)!=len(opportunities) or labels.observation_id.duplicated().any():raise ValueError('Label opportunity mismatch')
    save_parquet(HERE/'labels'/f'{cohort}-train_screen.parquet',labels)
    return labels

def join_labels(d,labels):
    cols=[c for c in labels.columns if c not in ['symbol','contract','decision_ts','side']]
    return d.merge(labels[cols],on='observation_id',how='left',validate='one_to_one')

def model_metadata(d,name,start,end,protocol_hash,market_hash):
    return {'name':name,'fit_start_ms':start,'fit_end_exclusive_ms':end,
            'fit_decision_min':int(d.decision_ts.min()),'fit_decision_max':int(d.decision_ts.max()),
            'fit_feature_known_max':int(d.feature_known_ts.max()),'fit_label_max':int(d.exit_ts_30.max()),
            'fit_label_end':int(d.exit_ts_30.max()),'fit_label60_max':int(d.exit_ts_60.max()),
            'all_60m_label_ends_strictly_before_boundary':bool(d.exit_ts_60.lt(end).all()),'purge_minutes':65,'frozen_after_fit':True,
            'protocol_sha256':protocol_hash,'market_manifest_sha256':market_hash,
            'fit_ids_sha256':id_hash(d.observation_id),'samples':sample_stats(d)}

def fit_pair(frame,group,target_name,extras,start,end,name,protocol_hash,market_hash):
    if not sample_stats(frame)['minimum_pass']:return None
    metadata=model_metadata(frame,name,start,end,protocol_hash,market_hash)
    if metadata['fit_label_max']>=end:raise ValueError('Future training target')
    a=fit_ols(frame,frame[target_name],BASE,metadata)
    b=fit_ols(frame,frame[target_name],BASE+extras,metadata)
    identifiable=(a['rank']==a['n_columns'] and b['rank']==b['n_columns'] and b['rank']>a['rank'])
    pair={'group':group,'target':target_name,'baseline':a,'enhanced':b,'identifiable':identifiable,
          'additional_rank':b['rank']-a['rank'],'extras':extras}
    save_json(HERE/'models'/f'{name}.json',pair)
    return pair

def phase3_group_frame(group,d,labels):
    mask=pd.read_parquet(PHASE2/'matched_samples'/f'{group}-mask.parquet')
    d=join_labels(d,labels).merge(mask[['observation_id','included']],on='observation_id',validate='one_to_one')
    d=d.rename(columns={'included':'phase2_included'})
    return d

def paired_split(d,name,start,end,group):
    a=d.loc[d.decision_ts.ge(start)&d.decision_ts.lt(end)].copy()
    a['within_purged_split']=temporal_mask(a,start,end)
    a['primary_label_valid']=a.label_valid_30.fillna(False).astype(bool)
    a['included']=a.phase2_included&a.within_purged_split&a.primary_label_valid
    if (a.loc[a.included,'exit_ts_30']>=end).any():raise ValueError('Target crosses boundary')
    cols=['observation_id','symbol','contract','decision_ts','phase2_included','within_purged_split','primary_label_valid','included','entry_ts','exit_ts_30','label_reason_30']
    save_parquet(HERE/'matched'/f'{group}-{name}.parquet',a[cols])
    usable=a.loc[a.included].copy()
    counts={'all_in_split':len(a),'phase2_feature_eligible':int(a.phase2_included.sum()),
            'purge_excluded_overlap':int((~a.within_purged_split).sum()),
            'invalid_label_among_feature_valid_and_purged':int((a.phase2_included&a.within_purged_split&~a.primary_label_valid).sum()),
            'label_reasons_after_feature_and_purge':a.loc[a.phase2_included&a.within_purged_split,'label_reason_30'].value_counts(dropna=False).to_dict(),
            'paired':sample_stats(usable),'baseline_ids_sha256':id_hash(usable.observation_id),
            'enhanced_ids_sha256':id_hash(usable.observation_id)}
    featurepurged=a.phase2_included&a.within_purged_split
    counts['label_attrition_by_horizon']={str(h):{'pre_label_eligible':int(featurepurged.sum()),
        'valid':int((featurepurged&a[f'label_valid_{h}'].fillna(False)).sum()),
        'reasons':a.loc[featurepurged,f'label_reason_{h}'].value_counts(dropna=False).to_dict()} for h in [15,30,60]}
    return usable,counts

def diagnostics(frame,group,split):
    rows=[]
    for h in [15,30,60]:
        q=frame.loc[frame[f'label_valid_{h}'].fillna(False)].copy()
        if len(q):
            q['month']=pd.to_datetime(q.decision_ts,unit='ms',utc=True).dt.strftime('%Y-%m')
            cols=[f'gross_bp_{h}',f'net20bp_proxy_{h}',f'mfe_bp_{h}',f'mae_bp_{h}']
            for by in ['all','side','symbol','month']:
                groups=[('all',q)] if by=='all' else q.groupby(by,observed=True)
                for key,g in groups:
                    item={'group':group,'split':split,'horizon':h,'stratum':by,'value':str(key),'records':len(g)}
                    item.update({c:float(g[c].mean()) for c in cols});rows.append(item)
    save_parquet(HERE/'diagnostics'/f'{group}-{split}.parquet',pd.DataFrame(rows))

def screen_group(group,cohorts,labels,protocol_hash,market_hash):
    cohort='events' if group in ['F4','F5'] else 'clock'
    d=phase3_group_frame(group,cohorts[cohort],labels[cohort])
    tr,tra=paired_split(d,'train',TRAIN_START,TRAIN_END,group)
    sc,sca=paired_split(d,'screen',TRAIN_END,SCREEN_END,group)
    target='mae_bp_30' if group=='F3' else 'gross_bp_30'
    result={'group':group,'cohort':cohort,'target':target,'increment_columns':GROUPS[group],
            'train':tra,'screen':sca,'p_raw':1.,'assessable':False,'selected':False,
            'status':'exploratory chronological historical selection; not pristine OOS',
            'gross_label_unit':'basis points','cost_proxy':'gross minus fixed 20 bp, no funding; not account returns'}
    phase2summary=json.loads((PHASE2/'matched_samples'/'summary.json').read_text(encoding='utf-8'))
    quality=next(q for q in phase2summary['groups'] if q['group']==group)
    result['phase2_quality_gate']={'feature_coverage':quality['group_feature_coverage'],
        'matched_coverage':quality['matched_share_of_feature_eligible'],'threshold':.8,
        'scope':'Frozen phase2 full period, not a new per-split coverage gate; pre-outcome clarification.'}
    quality_pass=bool(quality['feature_coverage_threshold_pass'] and quality['matched_coverage_threshold_pass'])
    pair=fit_pair(tr,group,target,GROUPS[group],TRAIN_START,TRAIN_END,f'{group}-train',protocol_hash,market_hash)
    if quality_pass and pair and pair['identifiable'] and sample_stats(sc)['minimum_pass']:
        bp,okb,newb=predict_ols(sc,pair['baseline']);ep,oke,newe=predict_ols(sc,pair['enhanced'])
        if not (okb&oke).all():raise ValueError('Different effective baseline/enhanced evaluation rows')
        daily=daily_loss(sc,sc[target],bp,ep,TRAIN_END,SCREEN_END)
        test=block_test(daily.difference)
        result.update(test);result['assessable']=True
        result['baseline_mean_loss']=float(daily.loss_base.mean())
        result['enhanced_mean_loss']=float(daily.loss_enhanced.mean())
        result['relative_loss_improvement']=float(daily.difference.mean()/daily.loss_base.mean())
        result['unseen_coin_observations']=int(newb.sum())
        result['unseen_coins']=sorted(sc.loc[newb,'symbol'].astype(str).unique().tolist())
        result['rank_baseline']=pair['baseline']['rank'];result['rank_enhanced']=pair['enhanced']['rank']
        save_parquet(HERE/'daily_loss'/f'{group}-screen.parquet',daily.reset_index(names='utc_day_number'))
        p=sc[['observation_id','symbol','contract','decision_ts','side',target,'exit_ts_30']].copy()
        p['baseline_prediction']=bp;p['enhanced_prediction']=ep;p['new_coin']=newb
        p['split']='screen';p['fit_label_end']=pair['baseline']['metadata']['fit_label_end']
        save_parquet(HERE/'screen_predictions'/f'{group}.parquet',p)
    else:
        result['not_assessable_reason']='minimum sample requirement or full/additional design rank failed'
    diagnostics(tr,group,'train');diagnostics(sc,group,'screen')
    return result

def eligible_event_design(d,extras,exclude_btc=False):
    values=design_values(d)
    ok=d.decision_valid.fillna(False).astype(bool)&d.side.isin([-1,1])
    ok &= np.isfinite(values[BASE+extras].to_numpy(float)).all(axis=1)
    if exclude_btc:ok &= d.symbol.ne('BTCUSDT')
    return ok

def refit_account(events,labels,selected,protocol_hash,market_hash):
    # Selection alone determines this union. No account/evaluation return is used.
    alpha=[g for g in selected if g!='F3'];extras=[c for g in alpha for c in GROUPS[g]]
    merged=join_labels(events,labels)
    eval_events=events.loc[events.decision_ts.ge(SCREEN_END)&events.decision_ts.lt(EVAL_END)].copy()
    p=eval_events[['observation_id','symbol','contract','decision_ts','side','feature_known_ts']].copy()
    p['split']='evaluation';p['alpha_available']=False;p['risk_available']=False
    p['account_common_available']=eval_events.decision_valid.fillna(False).astype(bool)
    for kind in ['alpha','risk']:
        p[kind+'_model_id']='';p[kind+'_fit_decision_end']=np.nan
        p[kind+'_fit_label_end']=np.nan;p[kind+'_unseen_coin']=False
    for c in ['alpha_baseline_prediction','alpha_enhanced_prediction','alpha_increment_prediction','risk_baseline_prediction','risk_enhanced_prediction','risk_increment_prediction']:
        p[c]=np.nan
    p['alpha_pass']=False;p['risk_multiplier']=1.
    report={'selected_groups':selected,'alpha_groups':alpha,'alpha_columns':extras,
            'event_transfer_not_prevalidated':True,'refit_start_ms':TRAIN_START,'refit_end_ms':SCREEN_END,
            'no_final_evaluation_labels_loaded':True,'alpha_model':None,'risk_model':None}
    for kind,incs,target,exclude in [('alpha',extras,'gross_bp_30','F1' in alpha),('risk',GROUPS['F3'],'mae_bp_30',False)]:
        enabled=bool(alpha) if kind=='alpha' else 'F3' in selected
        if not enabled:continue
        ok=eligible_event_design(merged,incs,exclude)&temporal_mask(merged,TRAIN_START,SCREEN_END)&merged.label_valid_30.fillna(False)
        # Original train/screen boundary remains purged even during the one Jan-Jun refit.
        ok &= ~((merged.decision_ts>=TRAIN_END-65*MINUTE)&(merged.decision_ts<TRAIN_END))
        fit=merged.loc[ok].copy()
        save_parquet(HERE/'matched'/f'joint-event-{kind}-refit.parquet',fit[['observation_id','symbol','contract','decision_ts','entry_ts','exit_ts_30']])
        pair=fit_pair(fit,f'joint_event_{kind}',target,incs,TRAIN_START,SCREEN_END,f'joint-event-{kind}-refit',protocol_hash,market_hash)
        report[kind+'_model']={'samples':sample_stats(fit),'assessable':bool(pair and pair['identifiable'])}
        if not pair or not pair['identifiable']:
            p['account_common_available']=False
            continue
        evalok=eligible_event_design(eval_events,incs,exclude)
        a,oka,new=predict_ols(eval_events,pair['baseline']);b,okb,_=predict_ols(eval_events,pair['enhanced'])
        available=evalok.to_numpy()&oka&okb
        p[kind+'_available']=available
        p['account_common_available'] &= available
        p[kind+'_baseline_prediction']=np.where(available,a,np.nan)
        p[kind+'_enhanced_prediction']=np.where(available,b,np.nan)
        p[kind+'_increment_prediction']=np.where(available,b-a,np.nan)
        p[kind+'_model_id']=f'joint-event-{kind}-refit'
        p[kind+'_fit_decision_end']=pair['baseline']['metadata']['fit_decision_max']
        p[kind+'_fit_label_end']=pair['baseline']['metadata']['fit_label_end']
        p[kind+'_unseen_coin']=new
        if kind=='alpha':p['alpha_pass']=available&(b>20)&((b-a)>0)
        else:p['risk_multiplier']=np.where(available&((b-a)>0),.5,1.)
    if not alpha:p['alpha_pass']=True
    p['selected_alpha_groups']=','.join(alpha);p['risk_group_selected']='F3' in selected
    p['protocol_sha256']=protocol_hash;p['market_manifest_sha256']=market_hash
    save_parquet(HERE/'predictions'/'account_events.parquet',p)
    report['prediction_rows']=len(p);report['alpha_available_rows']=int(p.alpha_available.sum())
    report['alpha_pass_rows']=int(p.alpha_pass.sum());report['risk_halved_rows']=int(p.risk_multiplier.eq(.5).sum())
    save_json(HERE/'account_refit.json',report)
    return report

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--frozen-protocol-sha256',required=True);args=ap.parse_args()
    protocol=PHASE3/'protocol.json'
    if not protocol.exists() or sha_file(protocol)!=args.frozen_protocol_sha256:raise RuntimeError('Explicit frozen protocol hash mismatch')
    if (HERE/'RESULTS_READY.json').exists():raise RuntimeError('Already ran; do not iterate on outcomes')
    # Authorized CLI hash + parent GO is mandatory; no result computation before this entry point.
    sys.path.insert(0,str(PHASE3/'account'));import market_io
    market=market_io.get_manifest();market_hash=sha_file(PHASE3/'account'/'market_manifest.json')
    frozen=json.loads(protocol.read_text(encoding='utf-8'))
    if market_hash!=frozen['data']['market_manifest_sha256']:raise ValueError('Frozen market hash mismatch')
    if sha_file(PHASE2/'data'/'manifest.json')!=frozen['data']['phase2_manifest_sha256']:raise ValueError('Frozen phase2 hash mismatch')
    source_paths=[Path(__file__),HERE/'methods.py',HERE/'test_methods.py',PHASE2/'feature_outputs'/'manifest.json',PHASE2/'data'/'manifest.json',PHASE2/'matched_samples'/'summary.json']
    source_hashes={str(p):sha_file(p) for p in source_paths}
    component=json.loads((HERE/'component_freeze.json').read_text(encoding='utf-8'))
    for path,expected in component['source_hashes'].items():
        if sha_file(path)!=expected:raise ValueError('Component changed after pre-outcome freeze: '+path)
    start=datetime.now(timezone.utc).isoformat()
    save_json(HERE/'RUN_STARTED.json',{'started_at_utc':start,'protocol_sha256':args.frozen_protocol_sha256,'source_hashes':source_hashes,'market_manifest_sha256':market_hash})
    cohorts={c:load_cohort(c) for c in ['clock','events']}
    labels={c:build_training_labels(c,cohorts[c],market_io) for c in ['clock','events']}
    print('Training/selection labels built; final evaluation labels are not requested.',flush=True)
    results=[]
    for group in GROUPS:
        r=screen_group(group,cohorts,labels,args.frozen_protocol_sha256,market_hash);results.append(r)
        print(group,'completed',flush=True)
    corrected=holm({r['group']:r['p_raw'] for r in results})
    for r in results:
        r['p_holm6']=corrected[r['group']]
        r['selected']=bool(r['assessable'] and r.get('mean_difference',0)>0 and r['p_holm6']<=.05)
    selected=[r['group'] for r in results if r['selected']]
    # Seal selection BEFORE fitting any account model and before opening evaluation outcomes.
    save_json(HERE/'selection.json',{'selected_groups':selected,'groups':results,'protocol_sha256':args.frozen_protocol_sha256,
                'selection_uses_only_train_and_screen':True,'final_evaluation_outcomes_loaded':False,
                'sealed_at_utc':datetime.now(timezone.utc).isoformat()})
    refit=refit_account(cohorts['events'],labels['events'],selected,args.frozen_protocol_sha256,market_hash)
    summary={'status':'completed','historical_exploratory_only':True,'primary_groups':6,'incremental_variables':10,
             'selected_groups':selected,'groups':results,'account_refit':refit,'protocol_sha256':args.frozen_protocol_sha256,
             'market_manifest_sha256':market_hash,'source_hashes':source_hashes,
             'label_counts':{c:{'opportunities':len(l),'valid_15':int(l.label_valid_15.sum()),'valid_30':int(l.label_valid_30.sum()),'valid_60':int(l.label_valid_60.sum())} for c,l in labels.items()},
             'final_evaluation_labels_loaded':False,'completed_at_utc':datetime.now(timezone.utc).isoformat()}
    save_json(HERE/'incremental_results.json',summary)
    save_json(HERE/'RESULTS_READY.json',{'summary_sha256':sha_file(HERE/'incremental_results.json'),'selection_sha256':sha_file(HERE/'selection.json'),
              'account_predictions_sha256':sha_file(HERE/'predictions'/'account_events.parquet'),'protocol_sha256':args.frozen_protocol_sha256})
    print(json.dumps({'selected_groups':selected,'results_file':str(HERE/'incremental_results.json')}),flush=True)

if __name__=='__main__':main()
