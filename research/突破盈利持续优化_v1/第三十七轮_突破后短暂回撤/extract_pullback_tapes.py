"""Reuse the audited public-tape loader with a separately frozen P10 pullback rule."""
import concurrent.futures,hashlib,json,shutil,sys,time
from pathlib import Path
import pandas as pd,psutil

HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
FOLLOW=PARENT/'第三十五轮_二次价格跟随';ORIG=PARENT/'第三十三轮_动态池逐笔执行'
sys.path.insert(0,str(FOLLOW));sys.path.insert(0,str(HERE))
import extract_follow_tapes as loader
from pullback_paths import simulate_pullback
PLAN=HERE/'冻结研究方案.json';SOURCE=HERE/'短暂回撤事前候选.parquet'
WORK=ROOT/'work'/'pullback37'/'tape';WORK.mkdir(parents=True,exist_ok=True)
FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+(HERE/'pullback_paths.py').read_bytes()+
    (FOLLOW/'extract_follow_tapes.py').read_bytes()+(ORIG/'leveraged_paths.py').read_bytes()+
    PLAN.read_bytes()+SOURCE.read_bytes()).hexdigest()

def guarded_task(spec):
    # Leave room for the user's existing applications and concurrent archives.
    while psutil.virtual_memory().available < 800*1024**2:time.sleep(3)
    return loader.task(spec)

def main():
    test=json.loads((HERE/'回撤入场时序与未来扰动核验.json').read_text(encoding='utf-8'))
    info=json.loads((HERE/'短暂回撤候选质量.json').read_text(encoding='utf-8'))
    d=pd.read_parquet(SOURCE)
    assert test['candidate_set_and_fields_unchanged'] and len(d)==test['all_candidates_checked']
    assert info['unknown_second_reference_events']==0 and info['plan_sha256']==hashlib.sha256(PLAN.read_bytes()).hexdigest()
    loader.WORK=WORK;loader.FINGERPRINT=FINGERPRINT;loader.simulate_follow=simulate_pullback
    orig=json.loads((ORIG/'动态池逐笔提取质量.json').read_text(encoding='utf-8'));expected={}
    for r in orig['archives']:
        if r['status']=='verified':
            expected[(r['contract'],r['day'],bool(r['needs_next']))]={x['day']:x['sha256'] for x in r['archives'] if x['kind']=='aggTrades'}
    tasks=[]
    for (contract,day,needs_next),g in d.groupby(['contract','day','needs_next']):
        k=(contract,day,bool(needs_next));assert k in expected
        tasks.append((contract,day,bool(needs_next),g.to_dict('records'),expected[k]))
    tasks.sort(key=lambda x:(0 if x[1]<'2024-05-01' else 1,x[1],x[0]));results=[]
    print('PULLBACK37_TAPE_TASKS',len(tasks),'candidate_events',len(d),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fs=[pool.submit(guarded_task,s) for s in tasks]
        for f in concurrent.futures.as_completed(fs):
            results.append(f.result())
            if len(results)%20==0:print('PULLBACK37_TAPES',len(results),'/',len(tasks),flush=True)
    rows=[];paths=[];archives=[]
    for r in results:
        archives.append({k:v for k,v in r.items() if k!='rows'})
        for row in r['rows']:
            for name,value in row.get('paths',{}).items():paths.append({'observation_id':row['observation_id'],'variant':name,**value})
            rows.append({'observation_id':row['observation_id'],'follow_status':row['status']})
    q=pd.DataFrame(rows);assert len(q)==len(d) and q.observation_id.is_unique
    paths=pd.DataFrame(paths);assert not paths.duplicated(['observation_id','variant']).any()
    paths.to_parquet(HERE/'动态池延迟市价路径.parquet',index=False)
    base=pd.read_parquet(ORIG/'动态池逐笔信号筛查.parquet');old_benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    base=base.merge(q,on='observation_id',how='left',validate='one_to_one');base['original_status']=base.status
    # no_follow_known is the shared engine's internal spelling for no P10 pullback order.
    base.loc[base.status.eq('qualified')&base.follow_status.isna(),'status']='no_follow_known'
    base.loc[base.follow_status.eq('verified'),'status']='qualified'
    base.loc[base.follow_status.notna()&~base.follow_status.eq('verified'),'status']='follow_data_error'
    base.loc[~base.original_status.isin(old_benign),'status']='upstream_data_unknown'
    base.to_parquet(HERE/'动态池逐笔信号筛查.parquet',index=False)
    benign=old_benign|{'no_follow_known'};unexpected=base[~base.status.isin(benign)]
    quality={'candidate_events':len(base),'pullback_candidates':len(d),'daily_tasks':len(tasks),
             'event_statuses':base.status.value_counts().to_dict(),'unexpected_event_count':len(unexpected),
             'variant_paths':len(paths),'unverified_path_count':int((~paths.status.eq('verified')).sum()),
             'archive_errors':[x for x in archives if x['status']!='verified'],'archives':archives,
             'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
             'fingerprint':FINGERPRINT,'note':'P10 is observed; entry starts after P10+5s. Upstream unknowns remain unknown.'}
    (HERE/'动态池逐笔提取质量.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copyfile(PLAN,HERE/'逐笔执行冻结方案.json')
    shutil.copyfile(ORIG/'不完整数据敏感性规则.json',HERE/'不完整数据敏感性规则.json')
    print('PULLBACK37_TAPES_COMPLETE',json.dumps({k:v for k,v in quality.items() if k!='archives'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
