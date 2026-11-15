"""Build retry-only 2024/2026 risk batches; unprocessed events remain unknown."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
import run_retests_later as runner
H=Path(__file__).resolve().parent;I=H/'跨期冻结输入';PREV=H.parent/'第四十六轮_固定十一加密币跨时段'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    f=json.loads((H/'跨期输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    oldmeta=json.loads((PREV/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'));oldplan=PREV/'逐笔冻结输入'/'old_execution_plan.json'
    assert sha(oldplan)==oldmeta['inputs']['old_execution_plan.json']
    summary=[]
    for year in ('2024','2026'):
        d=pd.read_parquet(I/f'{year}_retry_candidates.parquet');rows={};archives=[]
        for (sym,day,n),g in d.groupby(['contract','day','needs_next']):
            spec=(sym,day,bool(n),g.to_dict('records'));file=runner.WORK/(runner.key_for(spec)+'.json')
            if not file.exists():
                for obs in g.observation_id:rows[obs]={'observation_id':obs,'status':'archive_pending'}
                continue
            z=json.loads(file.read_text(encoding='utf-8'));assert z['status']=='verified';archives.append({k:v for k,v in z.items() if k!='rows'})
            for row in z['rows']:assert row['observation_id'] not in rows;rows[row['observation_id']]=row
        assert set(rows)==set(d.observation_id);out=H/f'{year}重试分批';out.mkdir(exist_ok=True)
        signals=[];paths=[]
        for obs,row in rows.items():
            pre=row.get('prechecks',{})
            for variant,value in row.get('paths',{}).items():paths.append({'observation_id':obs,'variant':variant,**value})
            signals.append({**{k:v for k,v in row.items() if k not in ('paths','prechecks')},'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
        s=pd.DataFrame(signals).merge(d,on='observation_id',validate='one_to_one',suffixes=('','_original'));p=pd.DataFrame(paths)
        if len(p):assert not p.duplicated(['observation_id','variant']).any()
        s.to_parquet(out/'动态池逐笔信号筛查.parquet',index=False);p.to_parquet(out/'动态池延迟市价路径.parquet',index=False)
        benign={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
        pending=sorted(s.loc[s.status.eq('archive_pending'),'observation_id'])
        meta={'candidate_events':len(s),'event_statuses':s.status.value_counts().to_dict(),
              'unexpected_event_count':int((~s.status.isin(benign)).sum()),'variant_paths':len(p),
              'unverified_path_count':int((~p.status.eq('verified')).sum()) if len(p) else 0,
              'archive_errors':[{'status':'archive_pending','events':pending}] if pending else [],'archives':archives,
              'note':'Only original known no-order candidates are retried; pending or source disagreement remains unknown.'}
        (out/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copyfile(oldplan,out/'逐笔执行冻结方案.json');summary.append({'year':year,**{k:v for k,v in meta.items() if k!='archives'}})
    print('RETEST47_LATER_BATCHES',json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
