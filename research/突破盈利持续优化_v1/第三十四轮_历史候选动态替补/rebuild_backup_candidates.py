"""Reuse old pre-rank events and rebuild extra symbol-days for backup ranks."""
import concurrent.futures,hashlib,json,shutil,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent;MIN_FREE=1_900_000_000
ORIG=PARENT/'第三十二轮_历史动态池分钟信号';sys.path.insert(0,str(ORIG))
import prepare_minute_candidates as previous
from minute_features import derive,M,H
WORK=ROOT/'work'/'point_in_time_universe34'/'events';WORK.mkdir(parents=True,exist_ok=True)
PLAN=HERE/'替补分钟候选冻结方案.json';BACKUP=HERE/'逐小时动态替补排名_待候选验证.parquet'
FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+PLAN.read_bytes()+BACKUP.read_bytes()+(ORIG/'minute_features.py').read_bytes()).hexdigest()
def task(spec):
    year,symbol,days=spec;digest=hashlib.sha256((FINGERPRINT+'|'+str(year)+'|'+symbol+'|'+','.join(days)).encode()).hexdigest()
    meta=WORK/(digest+'.json');event_path=WORK/(digest+'.parquet')
    if meta.exists() and event_path.exists():return json.loads(meta.read_text(encoding='utf-8'))
    start,end=('2023-12-01','2024-07-01') if year==2024 else ('2026-04-01','2026-08-01')
    months=(['2023-12']+[f'2024-{i:02}' for i in range(1,7)]) if year==2024 else [f'2026-{i:02}' for i in range(4,8)]
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000);hi=int(pd.Timestamp(end,tz='UTC').timestamp()*1000)
    grid=np.arange(lo,hi,M,dtype=np.int64);a=np.full((len(grid),7),np.nan);archives=[]
    for month in months:
        record,d=previous.get_month(symbol,month);archives.append(record)
        if record['status']=='error':return {'year':year,'symbol':symbol,'status':'error','archives':archives}
        if d is None:continue
        ix=((d.open_time.to_numpy(np.int64)-lo)//M).astype(np.int64)
        if (ix<0).any() or (ix>=len(grid)).any() or np.isfinite(a[ix,0]).any():raise ValueError('minute_grid_duplicate_or_outside')
        a[ix]=d[['open','high','low','close','volume','quote_volume','count']].to_numpy(float)
    _,events,counts=derive(a,grid,symbol,year,set(days))
    if shutil.disk_usage(ROOT).free<MIN_FREE:return {'year':year,'symbol':symbol,'status':'error','error':'disk_reserve','archives':archives}
    temp=event_path.with_suffix('.partial');pd.DataFrame(events).to_parquet(temp,index=False);temp.replace(event_path)
    out={'year':year,'symbol':symbol,'status':'verified','days':days,'archives':archives,'counts':counts,'event_path':str(event_path)}
    temp=meta.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(meta)
    return out
def main():
    backup=pd.read_parquet(BACKUP);old_daily=pd.read_parquet(PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet')
    oldpairs={(int(r.year),r.day,r.symbol) for r in old_daily.itertuples(index=False)}
    desired={(int(r.year),r.day,r.symbol) for r in backup.itertuples(index=False)}
    extra=desired-oldpairs;groups={}
    for year,day,symbol in extra:groups.setdefault((year,symbol),set()).add(day)
    specs=[(year,symbol,sorted(days)) for (year,symbol),days in sorted(groups.items())]
    print('UNIVERSE34_EXTRA_CANDIDATE_TASKS',len(specs),'symbol_days',len(extra),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fs=[pool.submit(task,s) for s in specs]
        for f in concurrent.futures.as_completed(fs):
            try:results.append(f.result())
            except Exception as exc:results.append({'status':'error','error':type(exc).__name__+':'+str(exc)[:120]})
            if len(results)%10==0:print('UNIVERSE34_EXTRA_CANDIDATES',len(results),'/',len(specs),flush=True)
    errors=[r for r in results if r['status']!='verified']
    if errors:
        (HERE/'替补分钟候选未完成.json').write_text(json.dumps({'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        print('UNIVERSE34_EXTRA_INCOMPLETE',json.dumps(errors,ensure_ascii=False),flush=True);return
    old_symbol_year={(int(r.year),r.symbol) for r in old_daily.itertuples(index=False)};pieces=[]
    for year,symbol in sorted(old_symbol_year):
        digest=hashlib.sha256((previous.FINGERPRINT+'|'+symbol+'|'+str(year)).encode()).hexdigest()
        path=previous.WORK/(digest+'.events.parquet');meta=previous.WORK/(digest+'.json')
        assert path.exists() and meta.exists(),(year,symbol,'original cache missing')
        z=pd.read_parquet(path)
        if len(z):pieces.append(z)
    for r in results:
        z=pd.read_parquet(r['event_path'])
        if len(z):pieces.append(z)
    events=pd.concat(pieces,ignore_index=True);assert events.observation_id.is_unique
    lookup={(int(r.decision_hour),r.symbol,int(r.side)):{'score':float(r.score),'rvol':float(r.rvol),
            'rank':int(r.hourly_rank),'liquidity_rank':int(r.rank),'available_pool_rank':int(r.eligible_pool_rank)}
            for r in backup.itertuples(index=False)}
    selected=[]
    for e in events.to_dict('records'):
        hour=int(e['trigger_minute'])//H*H
        for side,name in ((1,'long'),(-1,'short')):
            rank=lookup.get((hour,e['symbol'],side));good=bool(e[name+'_pre_rank'] and rank is not None)
            e[name+'_known_eligible']=good
            e[name+'_spec']=json.dumps({**json.loads(e[name+'_spec']),**rank},ensure_ascii=False) if good else 'null'
        if e['long_known_eligible'] or e['short_known_eligible']:selected.append(e)
    d=pd.DataFrame(selected).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
    assert d.observation_id.is_unique and not d.duplicated(['symbol','quarter_start']).any()
    d.to_parquet(HERE/'替补动态池潜在触价_待逐笔验证.parquet',index=False)
    out={'extra_symbol_year_tasks':len(specs),'extra_symbol_days':len(extra),'extra_sources_verified':len(results),
         'pre_rank_events':len(events),'potential_touch_events':len(d),'events_by_year':d.source_year.value_counts().to_dict(),
         'events_by_cohort':d.cohort.value_counts().to_dict(),'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
         'backup_rank_sha256':hashlib.sha256(BACKUP.read_bytes()).hexdigest(),
         'note':'Potential minutes only; first direction, actual fills, risk and account profitability are unverified.'}
    (HERE/'替补动态池候选质量.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=[{k:v for k,v in r.items() if k!='event_path'} for r in results]
    (HERE/'替补候选新增档案清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_BACKUP_EVENTS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
