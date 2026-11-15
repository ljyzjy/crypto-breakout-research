"""Merge both versions' verified checkpoints for the complete backup training slice."""
import json,shutil,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
OUT=HERE/'训练期分批';OUT.mkdir(parents=True,exist_ok=True)
def main():
    d=pd.read_parquet(HERE/'替补动态池潜在触价_待逐笔验证.parquet')
    cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    d=d[d.source_year.eq('2024')&(d.quarter_end+60_000<=cutoff)].copy();expected=set(d.observation_id)
    shared=json.loads((HERE/'共同候选复用独立核验.json').read_text(encoding='utf-8'));assert shared['all_signal_and_rules_match']
    records={};source_tasks=0
    for root in (ROOT/'work'/'point_in_time_universe33'/'tape',ROOT/'work'/'point_in_time_universe34'/'tape'):
      for f in sorted(root.glob('*.json')):
        z=json.loads(f.read_text(encoding='utf-8'))
        if z.get('status')!='verified':continue
        used=False
        for row in z['rows']:
            obs=row['observation_id']
            if obs not in expected:continue
            if obs in records:assert json.dumps(records[obs],sort_keys=True)==json.dumps(row,sort_keys=True),(obs,'conflicting checkpoints')
            else:records[obs]=row
            used=True
        source_tasks+=int(used)
    missing=expected-set(records)
    if missing:
        print('UNIVERSE34_TRAINING_CHECKPOINT_PROGRESS',len(records),'/',len(expected),'missing',len(missing),flush=True)
        if '--allow-pending' not in sys.argv:return
        for obs in sorted(missing):records[obs]={'observation_id':obs,'status':'archive_pending'}
    resolved=[]
    raw_files=[]
    for rawroot in (ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation',ROOT/'work'/'point_in_time_universe34'/'raw_reconciliation'):
        raw_files.extend(rawroot.glob('*.json'))
    for f in sorted(raw_files):
        batch=json.loads(f.read_text(encoding='utf-8'))
        if batch.get('status')!='verified':continue
        for item in batch['rows']:
            obs=item['observation_id']
            if obs not in records or not item.get('reconciled') or records[obs].get('status')!='minute_trade_ohlc_mismatch':continue
            records[obs]={'observation_id':obs,'original_source_status':'minute_trade_ohlc_mismatch',
                          'source_resolution':'strict_raw_reconciliation',**item['outcome']}
            resolved.append({'observation_id':obs,'checkpoint':str(f),'archives':batch['archives'],'checks':item.get('paths_checked',[])})
    rows=[];paths=[]
    for obs,row in records.items():
        ps=row.get('paths',{});pre=row.get('prechecks',{})
        for variant,value in ps.items():paths.append({'observation_id':obs,'variant':variant,**value})
        rows.append({**{k:v for k,v in row.items() if k not in ('paths','prechecks')},
                     'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
    signal=pd.DataFrame(rows).merge(d,on='observation_id',validate='one_to_one',suffixes=('','_candidate'));path=pd.DataFrame(paths)
    if len(path):assert not path.duplicated(['observation_id','variant']).any()
    signal.to_parquet(OUT/'动态池逐笔信号筛查.parquet',index=False);path.to_parquet(OUT/'动态池延迟市价路径.parquet',index=False)
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    meta={'candidate_events':len(d),'source_checkpoint_tasks':source_tasks,'strict_raw_reconciled_events':len(resolved),
          'event_statuses':signal.status.value_counts().to_dict(),
          'unexpected_event_count':int((~signal.status.isin(benign)).sum()),'variant_paths':len(path),
          'unverified_path_count':int((~path.status.eq('verified')).sum()) if len(path) else 0,
          'archive_errors':[{'status':'archive_pending','events':sorted(missing)}] if missing else [],
          'note':'Explicit pending candidates included; shared events passed input parity; no validation data in batch.' if missing else
                 'All predeclared backup training candidates present; shared events passed causal-input parity; no validation data in batch.'}
    (OUT/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'严格原始成交复核来源.json').write_text(json.dumps(resolved,ensure_ascii=False,indent=2),encoding='utf-8')
    orig=PARENT/'第三十三轮_动态池逐笔执行'
    shutil.copyfile(orig/'逐笔执行冻结方案.json',OUT/'逐笔执行冻结方案.json')
    shutil.copyfile(orig/'不完整数据敏感性规则.json',OUT/'不完整数据敏感性规则.json')
    shutil.copyfile(orig/'原始成交差异复核规则.json',OUT/'原始成交差异复核规则.json')
    shutil.copyfile(HERE/'替补逐笔执行冻结方案.json',OUT/'替补逐笔执行冻结方案.json')
    print('UNIVERSE34_TRAINING_BATCH_PROVISIONAL' if missing else 'UNIVERSE34_TRAINING_BATCH_READY',json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
