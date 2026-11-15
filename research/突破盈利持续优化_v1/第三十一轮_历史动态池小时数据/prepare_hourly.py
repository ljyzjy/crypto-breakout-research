"""Download verified historical hourly archives and prepare provisional causal ranks."""
import concurrent.futures,hashlib,io,json,shutil,threading,time,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
WORK=ROOT/'work'/'point_in_time_universe31'/'hourly';WORK.mkdir(parents=True,exist_ok=True)
H=3_600_000;MIN_FREE=1_900_000_000;BASE='https://data.binance.vision/'
PLAN=HERE/'小时数据与排名规则.json';FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+PLAN.read_bytes()).hexdigest()
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def parse(content,symbol,month):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names=z.namelist()
        if len(names)!=1 or not names[0].endswith('.csv'):raise ValueError('unexpected_zip_members')
        b=z.read(names[0]);first=b.splitlines()[0].decode('utf-8-sig')
    header=first.lower().startswith('open_time,')
    d=pd.read_csv(io.BytesIO(b),header=0 if header else None,names=None if header else COLS)
    required=['open_time','open','high','low','close','volume','close_time','quote_volume','count']
    if not set(required).issubset(d.columns):raise ValueError('unexpected_columns')
    d=d[required].apply(pd.to_numeric,errors='raise')
    if not np.isfinite(d.to_numpy(float)).all() or d.open_time.duplicated().any():raise ValueError('nonfinite_or_duplicate')
    if (d.open_time%H!=0).any() or (d.close_time!=d.open_time+H-1).any():raise ValueError('unexpected_hour_timestamps')
    if not pd.to_datetime(d.open_time,unit='ms',utc=True).dt.strftime('%Y-%m').eq(month).all():raise ValueError('out_of_month')
    price=(d[['open','high','low','close']]>0).all(axis=1)&d.high.ge(d[['open','low','close']].max(axis=1))&d.low.le(d[['open','high','close']].min(axis=1))
    valid=price&(d.volume>0)&(d.quote_volume>0)&(d['count']>0)
    d['valid']=valid;d['symbol']=symbol
    return d[['symbol','open_time','open','high','low','close','volume','quote_volume','count','valid']].to_dict('records')
def task(spec):
    symbol,year,month=spec;name=f'{symbol}-1h-{month}.zip';key=f'data/futures/um/monthly/klines/{symbol}/1h/{name}'
    ident=hashlib.sha256((FINGERPRINT+'|'+key).encode()).hexdigest();path=WORK/(ident+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        response=session().get(BASE+key+'.CHECKSUM',timeout=(15,50))
        if response.status_code==404:return {'symbol':symbol,'year':year,'month':month,'key':key,'status':'checksum_404','rows':[]}
        response.raise_for_status();digest=response.text.strip().split()[0].lower()
        response=session().get(BASE+key,timeout=(15,90));response.raise_for_status();b=response.content
        if hashlib.sha256(b).hexdigest()!=digest:raise ValueError('sha256_mismatch')
        out={'symbol':symbol,'year':year,'month':month,'key':key,'status':'verified','sha256':digest,'bytes':len(b),'rows':parse(b,symbol,month)}
        temp=path.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)
        return out
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:140]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'symbol':symbol,'year':year,'month':month,'key':key,'status':'error','error':error,'rows':[]}
def indicators(g,start,end):
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000);hi=int(pd.Timestamp(end,tz='UTC').timestamp()*1000)
    grid=np.arange(lo,hi,H,dtype=np.int64);x=g.set_index('open_time').reindex(grid)
    valid=x.valid.eq(True);close=x.close.where(valid).astype(float);quote=x.quote_volume.where(valid).astype(float)
    ret=np.log(close).diff();r6=ret.rolling(6,min_periods=6).sum();vol=ret.rolling(24,min_periods=24).std(ddof=1)
    lags=pd.concat([quote.shift(24*i) for i in range(1,21)],axis=1)
    med=lags.median(axis=1).where(lags.notna().all(axis=1))
    return pd.DataFrame({'decision_hour':grid+H,'score':(r6/vol.where(vol>0)).to_numpy(),
                         'rvol':(quote/med.where(med>0)).to_numpy(),'bar_valid':valid.to_numpy()})
def main():
    daily=pd.read_parquet(PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet')
    daily_quality=json.loads((PARENT/'第三十轮_历史币池数据准备'/'历史动态币池数据质量.json').read_text(encoding='utf-8'))
    assert not daily_quality['archive_errors']
    pools={int(y):sorted(g.symbol.unique()) for y,g in daily.groupby('year')}
    months={2024:['2023-12']+[f'2024-{i:02}' for i in range(1,7)],2026:[f'2026-{i:02}' for i in range(4,8)]}
    specs=[(symbol,year,month) for year in (2024,2026) for symbol in pools[year] for month in months[year]]
    print('UNIVERSE31_HOURLY_TASKS',len(specs),'symbols',sum(map(len,pools.values())),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        fs=[pool.submit(task,s) for s in specs]
        for fut in concurrent.futures.as_completed(fs):
            results.append(fut.result())
            if len(results)%100==0:print('UNIVERSE31_HOURLY',len(results),'/',len(specs),flush=True)
    errors=[{k:r[k] for k in ('symbol','year','month','key','error')} for r in results if r['status']=='error']
    missing=[{k:r[k] for k in ('symbol','year','month','key')} for r in results if r['status']=='checksum_404']
    rows=[{**z,'year':r['year']} for r in results for z in r['rows']]
    d=pd.DataFrame(rows,columns=['symbol','open_time','open','high','low','close','volume','quote_volume','count','valid','year'])
    assert not d.duplicated(['symbol','year','open_time']).any()
    d.to_parquet(HERE/'历史候选小时行情_原始可验证.parquet',index=False)
    features=[];groups={(int(year),symbol):g for (year,symbol),g in d.groupby(['year','symbol'])}
    for year in (2024,2026):
      for symbol in pools[year]:
        g=groups.get((year,symbol),d.iloc[:0])
        start,end=('2023-12-01','2024-07-01') if year==2024 else ('2026-04-01','2026-08-01')
        z=indicators(g,start,end);z['year']=year;z['symbol']=symbol;features.append(z)
    f=pd.concat(features,ignore_index=True)
    f['day']=pd.to_datetime(f.decision_hour,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    merged=daily[['year','day','symbol','rank']].merge(f,on=['year','day','symbol'],how='left',validate='one_to_many')
    assert len(merged)==24*len(daily),'missing per-hour coverage rows'
    eligible=merged[np.isfinite(merged.score)&np.isfinite(merged.rvol)&merged.rvol.ge(1.5)&merged.score.ne(0)].copy()
    eligible['side']=np.where(eligible.score>0,1,-1);eligible['strength']=eligible.score.abs()
    eligible=eligible.sort_values(['decision_hour','side','strength','rank','symbol'],ascending=[True,True,False,True,True])
    eligible['hourly_rank']=eligible.groupby(['decision_hour','side']).cumcount()+1
    top=eligible[eligible.hourly_rank<=3].copy()
    top.to_parquet(HERE/'历史动态池小时动量前三_待分钟核验.parquet',index=False)
    manifest=[{k:v for k,v in r.items() if k!='rows'} for r in results]
    (HERE/'小时档案状态清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    out={'tasks':len(specs),'verified_archives':sum(r['status']=='verified' for r in results),'checksum_404_count':len(missing),
         'errors':errors,'hourly_rows':len(d),'invalid_or_zero_rows':int((~d.valid).sum()),'candidate_hour_rows':len(merged),
         'candidate_hours_with_all_indicators':int((np.isfinite(merged.score)&np.isfinite(merged.rvol)).sum()),
         'provisional_top3_rows':len(top),'per_year_top3':{str(k):int(v) for k,v in top.groupby('year').size().to_dict().items()},
         'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
         'source_daily_rank_sha256':hashlib.sha256((PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet').read_bytes()).hexdigest(),
         'note':'Preliminary hourly bars only: old model requires all constituent minutes valid. Not complete signals or performance.'}
    (HERE/'小时数据准备质量.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE31_HOURLY_COMPLETE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
