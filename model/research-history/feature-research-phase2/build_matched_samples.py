"""Freeze identical baseline/enhanced observation sets without reading any future label."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
START=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
END=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)
GROUPS={'F1':('clock',['r6','residual6']), 'F2':('clock',['efficiency6','concentration6']),
 'F3':('clock',['rv_relative60','range_atr']), 'F4':('events',['boundary_distance','outside_fraction5']),
 'F5':('events',['drawdown_atr','recovery_fraction']), 'F6':('clock',['quote_rvol','count_rvol'])}
CONTROLS=['r6','btc_r6','vol24','quote_rvol']

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def truth(frame,key,default):
    return frame[key].fillna(False).astype(bool).to_numpy() if key in frame else np.full(len(frame),default,dtype=bool)
def finite(frame,cols):
    return np.isfinite(frame[cols].to_numpy(dtype=float)).all(axis=1)
def id_hash(ids):
    h=hashlib.sha256()
    for s in sorted(ids):h.update(s.encode('utf-8')+b'\n')
    return h.hexdigest()

def main():
    ready=json.loads((ROOT/'feature_outputs'/'READY.json').read_text(encoding='utf-8'))
    assert ready['ready'] and not ready['partial'],'Require the full frozen feature version'
    assert sha(ROOT/'feature_outputs'/'manifest.json')==ready['manifest_sha256']
    manifest=json.loads((ROOT/'feature_outputs'/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['source_manifest_sha256']==sha(ROOT/'data'/'manifest.json'),'Mixed input data version'
    assert manifest['features_sha256']==sha(ROOT/'features.py'),'Feature implementation changed since build'
    out=ROOT/'matched_samples';out.mkdir(exist_ok=True)
    marker=out/'READY.json'
    if marker.exists():marker.unlink()
    parent=json.loads((ROOT.parent/'feature-research-phase1'/'research_registration.json').read_text(encoding='utf-8'))
    summaries=[];source_hashes={};feature_coverage=[]
    for gid,(cohort,vars_) in GROUPS.items():
        paths=sorted((ROOT/'feature_outputs'/cohort).glob('*.parquet'))
        if not paths:raise RuntimeError('Feature cohort missing: '+cohort)
        masks=[];kept_metadata=[];total_reasons={};availability_total=0;group_total=0;original_total=0;original_available=0
        for path in paths:
            source_hashes[str(path.relative_to(ROOT)).replace('\\','/')]=sha(path)
            f=pd.read_parquet(path)
            if f.empty:continue
            needed=set(CONTROLS+vars_+['symbol','contract','decision_ts','side','eligible_decision','quarantined','minute_valid','source_max_known_ts','source_max_open_ts','hourly_known_ts'])
            if cohort=='events':needed.add('event_status')
            if missing:=needed-set(f.columns):raise ValueError((str(path),sorted(missing)))
            # Retain boundary-pending events in the mask, explicitly excluded by decision time.
            # Otherwise the source catalogue and comparison denominator would silently differ.
            f=f.reset_index(drop=True)
            if f.empty:continue
            ids=(f['event_id'].astype(str) if cohort=='events' else f['symbol'].astype(str)+'|'+f['decision_ts'].astype(str))
            if ids.duplicated().any():raise AssertionError('duplicate observation IDs '+str(path))
            eligible=truth(f,'eligible_decision',True)
            non_quarantined=~truth(f,'quarantined',False)
            raw_population=eligible&non_quarantined
            if gid=='F1':raw_population &= f.symbol.ne('BTCUSDT').to_numpy()
            available=finite(f,vars_)
            availability_total+=int((available&raw_population).sum());group_total+=int(raw_population.sum())
            original_population=f.symbol.ne('BTCUSDT').to_numpy() if gid=='F1' else np.ones(len(f),bool)
            original_total+=int(original_population.sum());original_available+=int((available&original_population).sum())
            for var in vars_:
                feature_coverage.append({'group':gid,'feature':var,'symbol':str(f.symbol.iloc[0]),'observations':int(raw_population.sum()),'available':int((np.isfinite(f[var].to_numpy(dtype=float))&raw_population).sum())})
            reasons={
              'not_eligible_at_decision':~eligible,
              'known_quarantine':~non_quarantined,
              'unmapped_perpetual':~truth(f,'mapped',True),
              'BTC_self_residual':f.symbol.eq('BTCUSDT').to_numpy() if gid=='F1' else np.zeros(len(f),bool),
              'invalid_current_minute':~truth(f,'minute_valid',True),
              'missing_or_zero_direction':~np.isfinite(f.side.to_numpy(dtype=float))|f.side.eq(0).to_numpy(),
              'missing_common_controls':~finite(f,CONTROLS),
              'missing_group_variables':~available,
              'tail_65min_purge':f.decision_ts.ge(END-65*60000).to_numpy(),
              'outside_development_decision':(~(f.decision_ts.ge(START)&f.decision_ts.lt(END))).to_numpy(),
            }
            if cohort=='events':reasons['event_not_measured']=f.event_status.ne('measured').to_numpy()
            # Decisions cannot use source observations that close after the decision.
            for key in ('source_max_known_ts','hourly_known_ts'):
                if key in f:
                    bad=f[key].notna()&f[key].gt(f.decision_ts)
                    if bad.any():raise AssertionError((path.name,key,'future source timestamp',int(bad.sum())))
            if 'source_max_open_ts' in f:
                bad=f.source_max_open_ts.notna()&(f.source_max_open_ts+60000>f.decision_ts)
                if bad.any():raise AssertionError((path.name,'unfinished minute input',int(bad.sum())))
            rejected=np.logical_or.reduce(list(reasons.values()))
            m=f[['symbol','contract','decision_ts']].copy();m.insert(0,'observation_id',ids.to_numpy())
            m['included']=~rejected
            for reason,flag in reasons.items():
                m[reason]=flag;total_reasons[reason]=total_reasons.get(reason,0)+int(flag.sum())
            masks.append(m)
            selected=f.loc[~rejected,['symbol','decision_ts']].copy();kept_metadata.append(selected)
        allm=pd.concat(masks,ignore_index=True) if masks else pd.DataFrame()
        assert not allm.observation_id.duplicated().any(),gid
        allm=allm.sort_values(['decision_ts','symbol','observation_id']).reset_index(drop=True)
        target=out/(gid+'-mask.parquet');temporary=out/(gid+'-mask.parquet.tmp')
        allm.to_parquet(temporary,index=False);temporary.replace(target)
        kept=allm[allm.included];ids=kept.observation_id.tolist();fingerprint=id_hash(ids)
        # One authoritative shared mask is intentionally used by both sides; neither can select separately.
        days=pd.to_datetime(kept.decision_ts,unit='ms',utc=True).dt.floor('D')
        weeks=days.dt.isocalendar();week_count=len(set(zip(weeks.year, weeks.week)))
        per_month=kept.assign(month=pd.to_datetime(kept.decision_ts,unit='ms',utc=True).dt.strftime('%Y-%m')).groupby('month').size().to_dict()
        per_symbol=kept.groupby('symbol').size().to_dict()
        min_=parent['causality_and_stability']['sample_min']
        sample_pass=(len(kept)>=min_['deduplicated_observations'] and days.nunique()>=min_['active_utc_days'] and week_count>=min_['distinct_active_utc_weeks'] and len(per_symbol)>=min_['symbols'])
        summaries.append({'group':gid,'cohort':cohort,'required_controls':CONTROLS,'required_group_variables':vars_,
          'all_cohort_records':len(allm),'feature_eligible_denominator':group_total,'group_features_available':availability_total,
          'original_cohort_denominator':original_total,'group_features_available_original_cohort':original_available,
          'original_cohort_feature_coverage':original_available/original_total if original_total else None,
          'matched_share_of_original_cohort':len(kept)/original_total if original_total else None,
          'group_feature_coverage':availability_total/group_total if group_total else None,'matched_observations':len(kept),
          'matched_share_of_feature_eligible':len(kept)/group_total if group_total else None,
          'feature_coverage_threshold_pass':bool(group_total and availability_total/group_total>=parent['causality_and_stability']['coverage_min']),
          'matched_coverage_threshold_pass':bool(group_total and len(kept)/group_total>=parent['causality_and_stability']['coverage_min']),
          'active_utc_days':int(days.nunique()),'distinct_active_utc_weeks':week_count,'symbols':len(per_symbol),
          'minimum_record_requirements_pass':bool(sample_pass),'per_month':{k:int(v) for k,v in per_month.items()},'per_symbol':{k:int(v) for k,v in per_symbol.items()},
          'attrition_overlapping_counts':total_reasons,'excluded_union':int((~allm.included).sum()),
          'shared_mask':target.name,'shared_mask_sha256':sha(target),'baseline_id_sha256':fingerprint,'enhanced_id_sha256':fingerprint,
          'identical_comparison_ids':True,'labels_materialized':False,
          'limitation':'Record minima are not independent-sample counts or statistical power. Future labels can reduce usable paired samples; identical per-group masks must then be rechecked before any results.'})
        print(gid,len(kept),'matched of',group_total,'eligible',flush=True)
    pd.DataFrame(feature_coverage).to_parquet(out/'feature-coverage-by-symbol.parquet',index=False)
    payload={'created_at_utc':datetime.now(timezone.utc).isoformat(),'groups':summaries,'input_feature_hashes':source_hashes,
      'data_manifest_sha256':sha(ROOT/'data'/'manifest.json'),'feature_manifest_sha256':sha(ROOT/'feature_outputs'/'manifest.json'),
      'period':{'start':START,'end_exclusive':END},'no_future_labels_computed':True,'no_alpha_gates_added':True,
      'coverage_denominator_note':'Each cohort retains its own opportunity denominator. F1 excludes BTC self-residual and reports total records too; no insufficient-history rows are silently removed from denominator. No six-group global intersection.',
      'attrition_note':'Reason counts overlap; sum is not total excluded. excluded_union gives distinct excluded records.'}
    (out/'summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    text=['统一比较样本：逐组共同掩码','本轮没有计算未来收益、MFE/MAE标签、回归拟合或账户回测。',
      '同一组的基准与增强读取同一份observation_id掩码，分别保留各组可用性；不把全部六组取交集。',
      '门槛按一期登记执行；边界65分钟按测量完成后的decision_ts计，后续构造收益标签还须检查label_end<边界。','']
    for s in summaries:
        text.append(f"{s['group']}：特征可用{s['group_features_available']:,}/{s['feature_eligible_denominator']:,}；控制变量/有效性/方向/边界共同限制后{s['matched_observations']:,}；{s['active_utc_days']}日，{s['symbols']}币；样本记录门槛{'通过' if s['minimum_record_requirements_pass'] else '不足'}。")
    text+=['','两个ID摘要相同仅证明本次比较入口一致，不证明后续模型/回测一定无误。事件组与时钟组的分母不同，不能把覆盖率直接当作因子强弱。',
      '原始资格、未匹配行与重叠的排除原因保留在每组mask；样本数不是独立信息量，后续仍须同步时间块推断。']
    (out/'比较样本说明.txt').write_text('\n'.join(text)+'\n',encoding='utf-8')
    marker.write_text(json.dumps({'ready':True,'summary_sha256':sha(out/'summary.json'),'builder_sha256':sha(Path(__file__)),'utc':datetime.now(timezone.utc).isoformat()},indent=2),encoding='utf-8')

if __name__=='__main__':main()
