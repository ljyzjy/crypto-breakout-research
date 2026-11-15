"""Re-fetch verified public tapes and execute P10 signal at a later P15 reference."""
import ast,concurrent.futures,hashlib,io,json,shutil,threading,time
from pathlib import Path
import pandas as pd,requests
from follow_paths import simulate_follow
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
ORIG=PARENT/'第三十三轮_动态池逐笔执行';SOURCE=HERE/'二次跟随事前候选.parquet';PLAN=HERE/'冻结研究方案.json'
WORK=ROOT/'work'/'follow35'/'tape';WORK.mkdir(parents=True,exist_ok=True)
# Preserve the original checkpoint keys when changing concurrency only.
FINGERPRINT='94b3f03eb6c93680dc11fbe1f0b3a7d0a2fa7962b75c0207078e0659d59329c0'
BASE='https://data.binance.vision/data/futures/um/daily/aggTrades/';MIN_FREE=1_900_000_000;local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(spec):
    contract,day,needs_next,events,expected=spec
    digest=hashlib.sha256((FINGERPRINT+'|'+contract+'|'+day+'|'+str(needs_next)+'|'+
             '|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest();path=WORK/(digest+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        days=[day]
        if needs_next:days.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        blocks={e['observation_id']:[] for e in events};archives=[]
        for date in days:
            name=f'{contract}-aggTrades-{date}.zip';url=f'{BASE}{contract}/{name}'
            c=session().get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
            if expected.get(date)!=sha:raise ValueError('source_archive_changed')
            r=session().get(url,timeout=(15,120));r.raise_for_status()
            if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('checksum_mismatch')
            archives.append({'day':date,'sha256':sha,'bytes':len(r.content)})
            for chunk in pd.read_csv(io.BytesIO(r.content),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=150_000):
                ts=chunk.transact_time.to_numpy('int64')
                for e in events:
                    z=chunk.loc[(ts>=int(e['trigger_minute']))&(ts<int(e['quarter_end'])+60_000)]
                    if len(z):blocks[e['observation_id']].append(z)
        rows=[]
        for e in events:
            parts=blocks[e['observation_id']]
            if not parts:rows.append({'observation_id':e['observation_id'],'status':'missing_tape','paths':{}});continue
            ticks=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort');paths={}
            for L in (10,20):
                if e[f'eligible_{L}x']:
                    for fail in (False,True):
                        name=('fast_2r_' if fail else 'normal_2r_')+str(L)+'x'
                        paths[name]=simulate_follow(e,ticks,L,fail)
            rows.append({'observation_id':e['observation_id'],'status':'verified' if all(x['status']=='verified' for x in paths.values()) else 'path_error','paths':paths})
        out={'contract':contract,'day':day,'needs_next':needs_next,'status':'verified','archives':archives,'rows':rows}
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        temp=path.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)
        return out
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:140]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs_next,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error','paths':{}} for e in events]}
def main():
    tree=ast.parse(Path(__file__).read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('session','task')]
    logic=ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False).encode()
    signature=hashlib.sha256(logic+(HERE/'follow_paths.py').read_bytes()+(ORIG/'leveraged_paths.py').read_bytes()+PLAN.read_bytes()+SOURCE.read_bytes()).hexdigest()
    assert signature=='147ec7b1291db535b1862ca5c6584853f5200f5067abb527f1eb27bf1463d899'
    assert BASE=='https://data.binance.vision/data/futures/um/daily/aggTrades/' and MIN_FREE==1_900_000_000
    nofuture=json.loads((HERE/'二次跟随未来扰动核验.json').read_text(encoding='utf-8'));d=pd.read_parquet(SOURCE)
    assert nofuture['candidate_set_and_fields_unchanged'] and len(d)==nofuture['all_candidates_checked']
    orig=json.loads((ORIG/'动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    expected={}
    for r in orig['archives']:
        if r['status']!='verified':continue
        expected[(r['contract'],r['day'],bool(r['needs_next']))]={x['day']:x['sha256'] for x in r['archives'] if x['kind']=='aggTrades'}
    tasks=[]
    for (c,day,n),g in d.groupby(['contract','day','needs_next']):
        key=(c,day,bool(n));assert key in expected
        tasks.append((c,day,bool(n),g.to_dict('records'),expected[key]))
    tasks.sort(key=lambda x:(0 if x[1]<'2024-05-01' else 1,x[1],x[0]))
    print('FOLLOW35_TAPE_TASKS',len(tasks),'candidate_events',len(d),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(task,x) for x in tasks]
        for f in concurrent.futures.as_completed(fs):
            results.append(f.result())
            if len(results)%20==0:print('FOLLOW35_TAPES',len(results),'/',len(tasks),flush=True)
    rows=[];paths=[];archives=[]
    for r in results:
        archives.append({k:v for k,v in r.items() if k!='rows'})
        for row in r['rows']:
            for name,value in row.get('paths',{}).items():paths.append({'observation_id':row['observation_id'],'variant':name,**value})
            rows.append({'observation_id':row['observation_id'],'follow_status':row['status']})
    q=pd.DataFrame(rows);assert len(q)==len(d) and q.observation_id.is_unique
    paths=pd.DataFrame(paths)
    if len(paths):assert not paths.duplicated(['observation_id','variant']).any()
    paths.to_parquet(HERE/'动态池延迟市价路径.parquet',index=False)
    base=pd.read_parquet(ORIG/'动态池逐笔信号筛查.parquet');old_benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    base=base.merge(q,on='observation_id',how='left',validate='one_to_one');base['original_status']=base.status
    base.loc[base.status.eq('qualified')&base.follow_status.isna(),'status']='no_follow_known'
    base.loc[base.follow_status.eq('verified'),'status']='qualified'
    base.loc[base.follow_status.notna()&~base.follow_status.eq('verified'),'status']='follow_data_error'
    base.loc[~base.original_status.isin(old_benign),'status']='upstream_data_unknown'
    base.to_parquet(HERE/'动态池逐笔信号筛查.parquet',index=False)
    benign=old_benign|{'no_follow_known'};unexpected=base[~base.status.isin(benign)]
    quality={'candidate_events':len(base),'follow_candidates':len(d),'daily_tasks':len(tasks),'event_statuses':base.status.value_counts().to_dict(),
             'unexpected_event_count':len(unexpected),'variant_paths':len(paths),
             'unverified_path_count':int((~paths.status.eq('verified')).sum()) if len(paths) else 0,
             'archive_errors':[x for x in archives if x['status']!='verified'],'archives':archives,
             'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
             'note':'P10 is observed, entry starts after P10+5s. Upstream unknowns remain unknown; no PnL or account inference.'}
    (HERE/'动态池逐笔提取质量.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copyfile(PLAN,HERE/'逐笔执行冻结方案.json')
    shutil.copyfile(ORIG/'不完整数据敏感性规则.json',HERE/'不完整数据敏感性规则.json')
    print('FOLLOW35_TAPES_COMPLETE',json.dumps({k:v for k,v in quality.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
