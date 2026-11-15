"""Verify only backup-only candidates with the exact earlier tick engine."""
import ast,concurrent.futures,hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
ORIG=PARENT/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(ORIG))
import extract_dynamic_tapes as engine
WORK=ROOT/'work'/'point_in_time_universe34'/'tape';WORK.mkdir(parents=True,exist_ok=True)
PLAN=HERE/'替补逐笔执行冻结方案.json'
def main():
    strict=pd.read_parquet(PARENT/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet')
    backup=pd.read_parquet(HERE/'替补动态池潜在触价_待逐笔验证.parquet')
    audit=json.loads((HERE/'替补动态候选独立核验.json').read_text(encoding='utf-8'))
    assert len(backup)==audit['all_candidate_gates_checked'] and strict.observation_id.is_unique and backup.observation_id.is_unique
    a=strict.set_index('observation_id');b=backup.set_index('observation_id');assert set(a.index)<=set(b.index)
    compare_keys=['upper','lower','atr','prior_prefix_ratio','prior_body_atr']
    for obs,x in a.iterrows():
        y=b.loc[obs]
        for k in compare_keys:assert np.isclose(float(x[k]),float(y[k]),rtol=1e-10,atol=1e-10),(obs,k)
        for name in ('long','short'):
            assert bool(x[name+'_known_eligible'])==bool(y[name+'_known_eligible']),(obs,name)
            if x[name+'_known_eligible']:
                s=json.loads(x[name+'_spec']);t=json.loads(y[name+'_spec'])
                for k in ('stop_price','level','score','rvol','rank','liquidity_rank'):
                    assert np.isclose(float(s[k]),float(t[k]),rtol=1e-10,atol=1e-10),(obs,name,k)
    d=backup[~backup.observation_id.isin(set(strict.observation_id))].copy();assert d.observation_id.is_unique
    d.to_parquet(HERE/'替补独有潜在触价.parquet',index=False)
    engine.WORK=WORK
    # Concurrency-only change: preserve original checkpoint keys, while
    # verifying the frozen inputs and all underlying archive/path routines.
    tree=ast.parse((ORIG/'extract_dynamic_tapes.py').read_text(encoding='utf-8'))
    nodes=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in ('archive','minute_bars','task')]
    logic=ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False).encode()
    signature=hashlib.sha256(logic+PLAN.read_bytes()+(ORIG/'tape_decision.py').read_bytes()+
                             (ORIG/'leveraged_paths.py').read_bytes()+(HERE/'替补独有潜在触价.parquet').read_bytes()).hexdigest()
    assert signature=='e62ffa9421cb79ade02d1d8535de2dd1acdae7e3ef74c470c0950d71fa632ad2'
    engine.FINGERPRINT='b5ed3d463e2880855df8e68fd0e778d4265d4ae6070494e78ba378f03f534ec7'
    d['needs_next']=(d.quarter_end+60_000-1)//86_400_000>d.trigger_minute//86_400_000
    tasks=[(c,day,bool(n),g.to_dict('records')) for (c,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda t:(t[1],t[0],t[2]))
    print('UNIVERSE34_TAPE_TASKS',len(tasks),'extra_events',len(d),'reused_events',len(strict),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fs=[pool.submit(engine.task,s) for s in tasks]
        for f in concurrent.futures.as_completed(fs):
            results.append(f.result())
            if len(results)%20==0:print('UNIVERSE34_TAPES',len(results),'/',len(tasks),flush=True)
    rows=[];paths=[];archives=[]
    for result in results:
        archives.append({k:v for k,v in result.items() if k!='rows'})
        for row in result['rows']:
            ps=row.pop('paths',{});pre=row.pop('prechecks',{})
            for v,value in ps.items():paths.append({'observation_id':row['observation_id'],'variant':v,**value})
            rows.append({**row,'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
    decisions=pd.DataFrame(rows);assert len(decisions)==len(d) and decisions.observation_id.is_unique
    decisions=decisions.merge(d,on='observation_id',validate='one_to_one',suffixes=('','_candidate'))
    decisions.to_parquet(HERE/'替补新增逐笔信号.parquet',index=False)
    paths=pd.DataFrame(paths)
    if len(paths):assert not paths.duplicated(['observation_id','variant']).any()
    paths.to_parquet(HERE/'替补新增延迟市价路径.parquet',index=False)
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    out={'strict_overlap_events':len(strict),'overlap_eligibility_and_rule_parity':True,'extra_events':len(d),'daily_tasks':len(tasks),
         'statuses':decisions.status.value_counts().to_dict(),'unexpected_event_count':int((~decisions.status.isin(benign)).sum()),
         'variant_paths':len(paths),'path_statuses':paths.status.value_counts().to_dict() if len(paths) else {},
         'unverified_path_count':int((~paths.status.eq('verified')).sum()) if len(paths) else 0,
         'archive_errors':[x for x in archives if x['status']!='verified'],'archives':archives,
         'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
         'note':'Only extra candidates here; reuse still requires the completed strict run. No account or costed PnL.'}
    (HERE/'替补新增逐笔质量.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_EXTRA_TAPES_COMPLETE',json.dumps({k:v for k,v in out.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
