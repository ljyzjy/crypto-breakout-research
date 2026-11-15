"""Assemble a training-only follow batch, retaining all upstream unknown events."""
import json,shutil,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
ORIG=PARENT/'第三十三轮_动态池逐笔执行';WORK=ROOT/'work'/'follow35'/'tape';OUT=HERE/'训练期分批';OUT.mkdir(parents=True,exist_ok=True)
def main():
    cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    follow=pd.read_parquet(HERE/'二次跟随事前候选.parquet');follow=follow[follow.source_year.eq('2024')&(follow.quarter_end+60_000<=cutoff)]
    base=pd.read_parquet(ORIG/'动态池逐笔信号筛查.parquet');base=base[base.source_year.eq('2024')&(base.quarter_end+60_000<=cutoff)].copy()
    expected=set(follow.observation_id);records={};tasks=0
    for p in sorted(WORK.glob('*.json')):
        z=json.loads(p.read_text(encoding='utf-8'));used=False
        if z.get('status')!='verified':continue
        for row in z['rows']:
            if row['observation_id'] not in expected:continue
            if row['observation_id'] in records:assert json.dumps(records[row['observation_id']],sort_keys=True)==json.dumps(row,sort_keys=True)
            else:records[row['observation_id']]=row
            used=True
        tasks+=int(used)
    missing=expected-set(records)
    if missing:
        print('FOLLOW35_TRAIN_CHECKPOINT_PROGRESS',len(records),'/',len(expected),'missing',len(missing),flush=True)
        if '--allow-pending' not in sys.argv:return
        for obs in sorted(missing):records[obs]={'observation_id':obs,'status':'archive_pending','paths':{}}
    rows=[];paths=[]
    for obs,r in records.items():
        rows.append({'observation_id':obs,'follow_status':r['status']})
        for v,z in r['paths'].items():paths.append({'observation_id':obs,'variant':v,**z})
    q=pd.DataFrame(rows);base=base.merge(q,on='observation_id',how='left',validate='one_to_one');base['original_status']=base.status
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    base.loc[base.status.eq('qualified')&base.follow_status.isna(),'status']='no_follow_known'
    base.loc[base.follow_status.eq('verified'),'status']='qualified'
    base.loc[base.follow_status.notna()&~base.follow_status.eq('verified'),'status']='follow_data_error'
    base.loc[~base.original_status.isin(benign),'status']='upstream_data_unknown'
    path=pd.DataFrame(paths);assert not path.duplicated(['observation_id','variant']).any()
    base.to_parquet(OUT/'动态池逐笔信号筛查.parquet',index=False);path.to_parquet(OUT/'动态池延迟市价路径.parquet',index=False)
    benign.add('no_follow_known')
    meta={'candidate_events':len(base),'follow_candidates':len(follow),'source_checkpoint_tasks':tasks,
          'event_statuses':base.status.value_counts().to_dict(),'unexpected_event_count':int((~base.status.isin(benign)).sum()),
          'variant_paths':len(path),'unverified_path_count':int((~path.status.eq('verified')).sum()),
          'archive_errors':[{'status':'archive_pending','events':sorted(missing)}] if missing else [],
          'note':'Training-only snapshot; pending follow tapes and upstream data mismatches remain unknown.'}
    (OUT/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copyfile(HERE/'冻结研究方案.json',OUT/'逐笔执行冻结方案.json')
    shutil.copyfile(ORIG/'不完整数据敏感性规则.json',OUT/'不完整数据敏感性规则.json')
    print('FOLLOW35_TRAIN_BATCH_PROVISIONAL' if missing else 'FOLLOW35_TRAIN_BATCH_READY',json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
