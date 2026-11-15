"""Checkpointed public-tape extraction for causal delayed unit paths."""
import concurrent.futures,hashlib,importlib.util,io,json,shutil,sys,threading,time
from pathlib import Path
import numpy as np,pandas as pd,requests
from unit_paths import known_precheck,simulate_path
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent;M=60_000
WORK=ROOT/'work'/'breakout_seconds_unit29'/'checkpoints';WORK.mkdir(parents=True,exist_ok=True)
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
sp=importlib.util.spec_from_file_location('unit29_config',PARENT/'第二十八轮_原十八币池扩展'/'generate_18_candidates.py')
config=importlib.util.module_from_spec(sp);sys.modules[sp.name]=config;sp.loader.exec_module(config)
local=threading.local();MIN_FREE=1_900_000_000
PATHS=[('normal_1r',1.,False),('fast_1r',1.,True),('normal_2r',2.,False),('fast_2r',2.,True)]
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def digest_task(contract,day,needs_next,events):
    h=hashlib.sha256();h.update((HERE/'冻结研究计划.json').read_bytes());h.update((HERE/'unit_paths.py').read_bytes())
    h.update(Path(__file__).read_bytes())
    h.update((contract+'|'+day+'|'+str(needs_next)).encode())
    for e in sorted(events,key=lambda x:x['observation_id']):
        keys=['observation_id','archive_sha256','side','stop_price','level','atr','upper','lower','trigger_minute',
              'quarter_end','decision_ts','signal_close','entry_exec_ts','raw_entry_5s']
        h.update(json.dumps({k:e[k] for k in keys},sort_keys=True,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)).encode())
    return h.hexdigest()
def task(spec):
    contract,day,needs_next,events=spec;digest=digest_task(contract,day,needs_next,events);checkpoint=WORK/(digest+'.json')
    if checkpoint.exists():
        cached=json.loads(checkpoint.read_text(encoding='utf-8'))
        if cached.get('task_digest')==digest:return {**cached,'checkpoint_reused':True}
    error='unknown'
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('insufficient_disk_reserve')
        blocks={e['observation_id']:[] for e in events}
        dates=[day]
        if needs_next:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        archives=[];total_bytes=0
        for this_day in dates:
            name=f'{contract}-aggTrades-{this_day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
            ch=session().get(url+'.CHECKSUM',timeout=(15,45));ch.raise_for_status();sha=ch.text.strip().split()[0].lower()
            if this_day==day and any(e['archive_sha256']!=sha for e in events):raise ValueError('archive_changed_since_source')
            response=session().get(url,timeout=(15,120));response.raise_for_status();body=response.content
            if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('checksum_mismatch')
            archives.append({'day':this_day,'sha256':sha,'bytes':len(body)});total_bytes+=len(body)
            for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=150_000):
                t=chunk.transact_time.to_numpy(np.int64)
                for e in events:
                    part=chunk.loc[(t>=int(e['trigger_minute']))&(t<int(e['quarter_end'])+60_000)]
                    if len(part):blocks[e['observation_id']].append(part)
        rows=[]
        for e in events:
            if not blocks[e['observation_id']]:
                rows.append({'observation_id':e['observation_id'],'status':'missing_event_tape'});continue
            tape=pd.concat(blocks[e['observation_id']],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            paths={name:simulate_path(e,tape,target,fail) for name,target,fail in PATHS}
            rows.append({'observation_id':e['observation_id'],'status':'verified' if all(x['status']=='verified' for x in paths.values()) else 'path_error',
                         'paths':paths,'archive_sha256':archives[0]['sha256'],'archives':archives})
        result={'contract':contract,'day':day,'needs_next':needs_next,'status':'verified','archives':archives,'bytes':total_bytes,'task_digest':digest,'rows':rows}
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('insufficient_disk_reserve')
        tmp=checkpoint.with_suffix('.partial');tmp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(checkpoint)
        return {**result,'checkpoint_reused':False}
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:120]
        if 'insufficient_disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'status':'error','error':error,'task_digest':digest,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error'} for e in events]}
def main():
    src=PARENT/'第二十八轮_原十八币池扩展'/'十八币首次触价五秒成交.parquet'
    d=pd.read_parquet(src)
    d=d[d.status.eq('verified')&d.five_status.eq('verified')&d.five_count.ge(3)&d.five_imbalance.ge(.1)&
        (d.side*(d.raw_entry_5s-d.level)>0)].copy()
    june_end=int(pd.Timestamp('2024-06-30',tz='UTC').timestamp()*1000)
    outside=(d.source_year.eq('2024')&d.decision_ts.ge(june_end));outside_count=int(outside.sum());d=d[~outside].copy()
    assert d.observation_id.is_unique
    excluded=[];kept=[]
    for year in (2024,2026):
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        for e in d[d.source_year.eq(str(year))].to_dict('records'):
            reason=known_precheck(e);ref_min=int(e['entry_exec_ts'])//M*M
            if reason is None and not guard.eligible(e['symbol'],int(e['side']),ref_min):reason='rank_or_trend_changed_known'
            if reason is None:
                prior=market.bar(e['contract'],ref_min-M);prior_mark=market.bar(e['contract'],ref_min-M,True)
                if prior is None or prior_mark is None or prior[4]<=0:reason='prior_data_unusable_known'
            if reason is None:kept.append(e)
            else:excluded.append({'observation_id':e['observation_id'],'reason':reason})
        del market,guard
    selected=pd.DataFrame(kept);assert selected.observation_id.is_unique
    selected['needs_next']=(selected.quarter_end+60_000-1)//86_400_000>selected.trigger_minute//86_400_000
    selected.to_parquet(HERE/'事前条件通过候选.parquet',index=False)
    tasks=[(c,day,bool(nextday),g.to_dict('records')) for (c,day,nextday),g in selected.groupby(['contract','day','needs_next'])]
    print('SECONDS29_TASKS',len(selected),'known_excluded',len(excluded),'archives',len(tasks),flush=True)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(task,x) for x in tasks]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            if len(results)%20==0:print('SECONDS29_ARCHIVES',len(results),'/',len(tasks),flush=True)
    rows=[row for result in results for row in result.pop('rows')];assert len(rows)==len(selected)
    flat=[]
    for row in rows:
        for name,_,_ in PATHS:
            p=row.get('paths',{}).get(name,{'status':row['status']})
            flat.append({'observation_id':row['observation_id'],'variant':name,'archive_sha256':row.get('archive_sha256'),**p})
    paths=pd.DataFrame(flat);assert not paths.duplicated(['observation_id','variant']).any()
    paths.to_parquet(HERE/'秒级路径与延迟参考.parquet',index=False)
    meta={'source_events_in_study_dates':len(d),'outside_predeclared_dates':outside_count,
          'prechecked_events':len(selected),'cross_utc_day_events':int(selected.needs_next.sum()),'known_excluded_count':len(excluded),'known_exclusions':excluded,
          'daily_archives':len(tasks),'verified_archives':sum(x['status']=='verified' for x in results),
          'checkpoint_reused':sum(bool(x.get('checkpoint_reused')) for x in results),
          'event_status_counts':pd.Series([x['status'] for x in rows]).value_counts().to_dict(),
          'path_status_counts':paths.status.value_counts().to_dict(),
          'archive_errors':[x for x in results if x['status']!='verified'],
          'bytes_downloaded':sum(x.get('bytes',0) for x in results if not x.get('checkpoint_reused')),
          'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'archives':results,
          'note':'Failure/success outcomes cannot be used to omit a bad tape or missed delayed reference.'}
    flow.dump(HERE/'秒级路径档案与排除记录.json',meta)
    print('SECONDS29_EXTRACT_COMPLETE',json.dumps({k:meta[k] for k in ['source_events_in_study_dates','outside_predeclared_dates','prechecked_events','cross_utc_day_events','known_excluded_count','daily_archives','event_status_counts','path_status_counts','bytes_downloaded','archive_errors']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
