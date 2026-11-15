"""Build a retry-only risk batch while leaving all pending events unknown."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
import run_retests_2023 as runner
H=Path(__file__).resolve().parent;I=H/'2023冻结输入';OUT=H/'2023重试分批';OUT.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    f=json.loads((H/'2023输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    d=pd.read_parquet(I/'retry_candidates.parquet');rows={};archives=[]
    for (sym,day,n),g in d.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));file=runner.WORK/(runner.key_for(spec)+'.json')
        if not file.exists():
            for obs in g.observation_id:rows[obs]={'observation_id':obs,'status':'archive_pending'}
            continue
        z=json.loads(file.read_text(encoding='utf-8'));assert z['status']=='verified';archives.append({k:v for k,v in z.items() if k!='rows'})
        for row in z['rows']:
            assert row['observation_id'] not in rows;rows[row['observation_id']]=row
    assert set(rows)==set(d.observation_id)
    signals=[];paths=[]
    for obs,row in rows.items():
        pre=row.get('prechecks',{})
        for variant,value in row.get('paths',{}).items():paths.append({'observation_id':obs,'variant':variant,**value})
        signals.append({**{k:v for k,v in row.items() if k not in ('paths','prechecks')},'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
    s=pd.DataFrame(signals).merge(d,on='observation_id',validate='one_to_one',suffixes=('','_original'))
    p=pd.DataFrame(paths)
    if len(p):assert not p.duplicated(['observation_id','variant']).any()
    s.to_parquet(OUT/'动态池逐笔信号筛查.parquet',index=False);p.to_parquet(OUT/'动态池延迟市价路径.parquet',index=False)
    benign={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
    pending=sorted(s.loc[s.status.eq('archive_pending'),'observation_id'])
    meta={'candidate_events':len(s),'event_statuses':s.status.value_counts().to_dict(),
          'unexpected_event_count':int((~s.status.isin(benign)).sum()),'variant_paths':len(p),
          'unverified_path_count':int((~p.status.eq('verified')).sum()) if len(p) else 0,
          'archive_errors':[{'status':'archive_pending','events':pending}] if pending else [],
          'archives':archives,'note':'Only original known no-order candidates are retried; pending or source disagreement remains unknown.'}
    (OUT/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copyfile(H.parent/'第四十三轮_旧十一币2023年复核'/'部分批次'/'逐笔执行冻结方案.json',OUT/'逐笔执行冻结方案.json')
    print('RETEST47_2023_BATCH',json.dumps({k:v for k,v in meta.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
