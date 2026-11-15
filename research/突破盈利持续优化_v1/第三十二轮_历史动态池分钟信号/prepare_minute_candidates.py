"""Stream checksum-verified minute archives and produce causal potential touches."""
import concurrent.futures,hashlib,importlib.util,io,json,shutil,sys,threading,time,zipfile
from collections import Counter
from pathlib import Path
import numpy as np,pandas as pd,requests
from minute_features import derive,M,H
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
WORK=ROOT/'work'/'point_in_time_universe32'/'symbols';WORK.mkdir(parents=True,exist_ok=True)
PLAN=HERE/'分钟候选生成方案.json';RANK=PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet'
FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+(HERE/'minute_features.py').read_bytes()+PLAN.read_bytes()+RANK.read_bytes()).hexdigest()
BASE='https://data.binance.vision/';MIN_FREE=1_900_000_000;local=threading.local()
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def parse(data,month):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist()
        if len(names)!=1 or not names[0].endswith('.csv'):raise ValueError('unexpected_zip_members')
        b=z.read(names[0]);head=b.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
    d=pd.read_csv(io.BytesIO(b),header=0 if head else None,names=None if head else COLS)
    needed=['open_time','open','high','low','close','volume','close_time','quote_volume','count']
    if not set(needed).issubset(d.columns):raise ValueError('unexpected_columns')
    d=d[needed].apply(pd.to_numeric,errors='raise')
    if not np.isfinite(d.to_numpy(float)).all() or d.open_time.duplicated().any():raise ValueError('nonfinite_or_duplicate')
    if (d.open_time%M!=0).any() or (d.close_time!=d.open_time+M-1).any():raise ValueError('minute_timestamps')
    if not pd.to_datetime(d.open_time,unit='ms',utc=True).dt.strftime('%Y-%m').eq(month).all():raise ValueError('out_of_month')
    return d
def get_month(symbol,month):
    name=f'{symbol}-1m-{month}.zip';key=f'data/futures/um/monthly/klines/{symbol}/1m/{name}'
    error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        ch=session().get(BASE+key+'.CHECKSUM',timeout=(15,50))
        if ch.status_code==404:return {'month':month,'key':key,'status':'checksum_404'},None
        ch.raise_for_status();sha=ch.text.strip().split()[0].lower()
        r=session().get(BASE+key,timeout=(15,100));r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('sha256_mismatch')
        d=parse(r.content,month)
        return {'month':month,'key':key,'status':'verified','sha256':sha,'bytes':len(r.content),'rows':len(d)},d
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:140]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'month':month,'key':key,'status':'error','error':error},None
def task(spec):
    symbol,year,pool_days=spec;ident=hashlib.sha256((FINGERPRINT+'|'+symbol+'|'+str(year)).encode()).hexdigest()
    meta_path=WORK/(ident+'.json');hours_path=WORK/(ident+'.hours.parquet');events_path=WORK/(ident+'.events.parquet')
    if meta_path.exists() and hours_path.exists() and events_path.exists():
        z=json.loads(meta_path.read_text(encoding='utf-8'))
        if z['fingerprint']==FINGERPRINT:return z
    start,end=('2023-12-01','2024-07-01') if year==2024 else ('2026-04-01','2026-08-01')
    months=(['2023-12']+[f'2024-{i:02}' for i in range(1,7)]) if year==2024 else [f'2026-{i:02}' for i in range(4,8)]
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000);hi=int(pd.Timestamp(end,tz='UTC').timestamp()*1000)
    grid=np.arange(lo,hi,M,dtype=np.int64);a=np.full((len(grid),7),np.nan);archives=[]
    for month in months:
        meta,d=get_month(symbol,month);archives.append(meta)
        if meta['status']=='error':return {'symbol':symbol,'year':year,'status':'error','archives':archives}
        if d is None:continue
        t=d.open_time.to_numpy(np.int64);ix=((t-lo)//M).astype(np.int64)
        if (ix<0).any() or (ix>=len(grid)).any() or np.isfinite(a[ix,0]).any():raise ValueError('minute_grid_duplicate_or_outside')
        a[ix]=d[['open','high','low','close','volume','quote_volume','count']].to_numpy(float)
    hour,events,counters=derive(a,grid,symbol,year,set(pool_days))
    if shutil.disk_usage(ROOT).free<MIN_FREE:return {'symbol':symbol,'year':year,'status':'error','error':'disk_reserve','archives':archives}
    htemp=hours_path.with_suffix('.partial');etemp=events_path.with_suffix('.partial')
    hour.to_parquet(htemp,index=False);pd.DataFrame(events).to_parquet(etemp,index=False)
    htemp.replace(hours_path);etemp.replace(events_path)
    out={'symbol':symbol,'year':year,'status':'verified','archives':archives,'counters':counters,
         'hour_path':str(hours_path),'event_path':str(events_path),'fingerprint':FINGERPRINT}
    temp=meta_path.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(meta_path)
    return out
def load_indicators():
    path=PARENT/'第三十一轮_历史动态池小时数据'/'prepare_hourly.py'
    spec=importlib.util.spec_from_file_location('strict_hourly31',path);module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module;spec.loader.exec_module(module);return module.indicators
def main():
    daily=pd.read_parquet(RANK);quality=json.loads((PARENT/'第三十轮_历史币池数据准备'/'历史动态币池数据质量.json').read_text(encoding='utf-8'))
    assert not quality['archive_errors'] and not daily.duplicated(['year','day','symbol']).any()
    specs=[(symbol,int(year),sorted(g.day.unique())) for (year,symbol),g in daily.groupby(['year','symbol'])]
    print('UNIVERSE32_SYMBOL_TASKS',len(specs),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(task,s) for s in specs]
        for fut in concurrent.futures.as_completed(fs):
            try:results.append(fut.result())
            except Exception as exc:results.append({'status':'error','error':type(exc).__name__+':'+str(exc)[:140]})
            if len(results)%10==0:print('UNIVERSE32_SYMBOLS',len(results),'/',len(specs),flush=True)
    errors=[r for r in results if r['status']!='verified']
    if errors:
        (HERE/'分钟数据准备未完成.json').write_text(json.dumps({'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        print('UNIVERSE32_INCOMPLETE',json.dumps(errors,ensure_ascii=False),flush=True);return
    hours=pd.concat([pd.read_parquet(r['hour_path']) for r in results],ignore_index=True)
    assert not hours.duplicated(['symbol','year','open_time']).any()
    hours.to_parquet(HERE/'一分钟严格合成小时.parquet',index=False)
    indicator=load_indicators();features=[]
    for (year,symbol),g in hours.groupby(['year','symbol']):
        start,end=('2023-12-01','2024-07-01') if year==2024 else ('2026-04-01','2026-08-01')
        z=indicator(g,start,end);z['year']=int(year);z['symbol']=symbol;features.append(z)
    f=pd.concat(features,ignore_index=True);f['day']=pd.to_datetime(f.decision_hour,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    merged=daily[['year','day','symbol','rank']].merge(f,on=['year','day','symbol'],how='left',validate='one_to_many')
    assert len(merged)==24*len(daily)
    merged['indicator_valid']=np.isfinite(merged.score)&np.isfinite(merged.rvol)
    merged['valid_pool_size']=merged.groupby('decision_hour').indicator_valid.transform('sum')
    complete=merged[merged.valid_pool_size.eq(20)].copy()
    eligible=complete[complete.indicator_valid&complete.rvol.ge(1.5)&complete.score.ne(0)].copy()
    eligible['side']=np.where(eligible.score>0,1,-1);eligible['strength']=eligible.score.abs()
    eligible=eligible.sort_values(['decision_hour','side','strength','rank','symbol'],ascending=[True,True,False,True,True])
    eligible['hourly_rank']=eligible.groupby(['decision_hour','side']).cumcount()+1
    top=eligible[eligible.hourly_rank<=3].copy()
    top.to_parquet(HERE/'分钟严格验证后动态池小时排名.parquet',index=False)
    lookup={(int(r.decision_hour),r.symbol,int(r.side)):{'score':float(r.score),'rvol':float(r.rvol),
            'rank':int(r.hourly_rank),'liquidity_rank':int(r.rank)} for r in top.itertuples(index=False)}
    pieces=[pd.read_parquet(r['event_path']) for r in results]
    pieces=[p for p in pieces if len(p)];events=pd.concat(pieces,ignore_index=True)
    assert events.observation_id.is_unique
    output=[]
    for e in events.to_dict('records'):
        hour=int(e['trigger_minute'])//H*H
        for side,name in ((1,'long'),(-1,'short')):
            details=lookup.get((hour,e['symbol'],side));eligible_side=bool(e[name+'_pre_rank'] and details is not None)
            e[name+'_known_eligible']=eligible_side
            if eligible_side:e[name+'_spec']=json.dumps({**json.loads(e[name+'_spec']),**details},ensure_ascii=False)
            else:e[name+'_spec']='null'
        if e['long_known_eligible'] or e['short_known_eligible']:output.append(e)
    selected=pd.DataFrame(output).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
    assert selected.observation_id.is_unique and not selected.duplicated(['symbol','quarter_start']).any()
    selected.to_parquet(HERE/'历史动态池潜在触价_待逐笔验证.parquet',index=False)
    counts=Counter()
    for r in results:counts.update(r['counters'])
    archive_status=Counter(a['status'] for r in results for a in r['archives'])
    unique_hours=int(merged.decision_hour.nunique());complete_hours=int(complete.decision_hour.nunique())
    manifest={'archive_status':dict(archive_status),'symbol_sources':[{k:v for k,v in r.items() if k not in ('hour_path','event_path')} for r in results]}
    (HERE/'分钟档案及候选排除记录.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    out={'symbol_year_tasks':len(specs),'archive_status':dict(archive_status),'hours':unique_hours,'hours_all_20_features_available':complete_hours,
         'hours_excluded_for_pool_coverage':unique_hours-complete_hours,'strict_top3_rank_rows':len(top),
         'pre_rank_candidates':len(events),'potential_touches_after_rank':len(selected),'candidate_year_counts':selected.source_year.value_counts().to_dict(),
         'candidate_cohorts':selected.cohort.value_counts().to_dict(),'counts':dict(counts),
         'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'daily_rank_sha256':hashlib.sha256(RANK.read_bytes()).hexdigest(),
         'note':'Potential touch only. Tick direction, five-second flow, costs, risk, fills and shared-account performance not yet established.'}
    (HERE/'动态池分钟候选质量.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE32_MINUTE_COMPLETE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
