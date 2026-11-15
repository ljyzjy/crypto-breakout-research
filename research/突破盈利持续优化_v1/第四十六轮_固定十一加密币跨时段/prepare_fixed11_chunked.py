"""Rebuild past-only fixed-11 daily/hourly rankings and candidate minute locations."""
import hashlib,importlib.util,json,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
from minute_features_fixed11 import M,H,Q
from chunk_exact import derive_chunked as derive
HERE=Path(__file__).resolve().parent;P=HERE.parent;ROOT=P.parent.parent
WORK=ROOT/'work'/'fixed11_cross46'/'chunked_symbols';WORK.mkdir(parents=True,exist_ok=True)
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
WINDOWS={2024:('2023-12-01','2024-01-01','2024-07-01'),2026:('2026-04-01','2026-05-01','2026-08-01')}
DAY=86_400_000
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def ms(s):return int(pd.Timestamp(s,tz='UTC').timestamp()*1000)
def hourly_indicator():
    path=P/'第三十一轮_历史动态池小时数据'/'prepare_hourly.py'
    spec=importlib.util.spec_from_file_location('fixed11_hourly46',path);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    return mod.indicators
def process(year,symbol,src,fp):
    start,begin,end=WINDOWS[year];lo=ms(start);hi=ms(end)
    key=hashlib.sha256((fp+'|'+str(year)+'|'+symbol).encode()).hexdigest();base=WORK/key
    meta=base.with_suffix('.json');hp=base.with_suffix('.hours.parquet');dp=base.with_suffix('.days.parquet');ep=base.with_suffix('.events.parquet');mp=base.with_suffix('.market.parquet')
    if all(x.exists() for x in (meta,hp,dp,ep)) and (symbol not in ('BTCUSDT','ETHUSDT') or mp.exists()):return json.loads(meta.read_text(encoding='utf-8'))
    while psutil.virtual_memory().available<350*1024**2:
        if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
        time.sleep(3)
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    d=pd.read_parquet(src);cols=['ts','open','high','low','close','volume','quote_volume','trade_count']
    assert set(cols).issubset(d.columns) and not d.ts.duplicated().any() and (d.ts%M==0).all()
    d=d[d.ts.between(lo,hi-1)];grid=np.arange(lo,hi,M,dtype=np.int64);a=np.full((len(grid),7),np.nan)
    ix=((d.ts.to_numpy(np.int64)-lo)//M).astype(int);assert len(np.unique(ix))==len(ix)
    a[ix]=d[cols[1:]].to_numpy(float);del d
    days=a.reshape(-1,1440,7);structural=np.isfinite(days).all(axis=(1,2))&(days[:,:,:4]>0).all(axis=(1,2))&(days[:,:,4:]>=0).all(axis=(1,2))
    quote=days[:,:,5].sum(axis=1);quote=np.where(structural&(quote>0),quote,np.nan)
    dates=pd.to_datetime(grid[::1440],unit='ms',utc=True).strftime('%Y-%m-%d')
    past=pd.Series(quote).shift(1).rolling(30,min_periods=30).sum().to_numpy()
    day=pd.DataFrame({'symbol':symbol,'day':dates,'past_30d_quote':past})
    pool=set(day.loc[day.day.ge(begin)&day.day.lt(end)&np.isfinite(day.past_30d_quote),'day'])
    hour,events,counters=derive(a,grid,symbol,year,pool)
    hour.to_parquet(hp,index=False);day.to_parquet(dp,index=False);pd.DataFrame(events).to_parquet(ep,index=False)
    if symbol in ('BTCUSDT','ETHUSDT'):
        quarter=a.reshape(-1,15,7);v=np.isfinite(quarter).all(axis=(1,2))&(quarter[:,:,:4]>0).all(axis=(1,2))&(quarter[:,:,4:]>=0).all(axis=(1,2))
        vol=quarter[:,:,4].sum(axis=1);count=quarter[:,:,6].sum(axis=1);v&=(vol>0)&(count>0)
        high=np.where(np.isfinite(quarter[:,:,1]),quarter[:,:,1],-np.inf).max(axis=1)
        low=np.where(np.isfinite(quarter[:,:,2]),quarter[:,:,2],np.inf).min(axis=1)
        market=pd.DataFrame({'symbol':symbol,'open_time':grid[::15][v],'open':quarter[:,0,0][v],
          'high':high[v],'low':low[v],'close':quarter[:,-1,3][v],'volume':vol[v],'count':count[v].astype(np.int64)})
        market.to_parquet(mp,index=False)
    out={'year':year,'symbol':symbol,'source_sha256':sha(src),'hours_path':str(hp),'days_path':str(dp),'events_path':str(ep),
         'market_path':str(mp) if symbol in ('BTCUSDT','ETHUSDT') else None,'counters':counters,'fingerprint':fp}
    meta.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return out
def main():
    frozen=json.loads((HERE/'小块来源冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(HERE/'冻结研究方案.md')==frozen['plan_sha256']
    for x in frozen['sources'].values():assert sha(Path(x['path']))==x['sha256']
    for x in frozen['code'].values():assert sha(Path(x['path']))==x['sha256']
    for x in frozen['support'].values():assert sha(Path(x['path']))==x['sha256']
    fp=hashlib.sha256((HERE/'小块来源冻结哈希.json').read_bytes()).hexdigest();indicator=hourly_indicator();summaries=[]
    for year,(start,begin,end) in WINDOWS.items():
        records=[]
        for sym in SYMBOLS:
            records.append(process(year,sym,Path(frozen['sources'][f'{year}_{sym}']['path']),fp))
            print('FIXED11_46_CHUNKED_SYMBOLS',year,len(records),'/',len(SYMBOLS),flush=True)
        out=HERE/str(year);out.mkdir(exist_ok=True)
        days=pd.concat([pd.read_parquet(r['days_path']) for r in records],ignore_index=True)
        days=days[days.day.ge(begin)&days.day.lt(end)&np.isfinite(days.past_30d_quote)].copy()
        days['eligible_count']=days.groupby('day').symbol.transform('size');days=days[days.eligible_count.eq(11)]
        days=days.sort_values(['day','past_30d_quote','symbol'],ascending=[True,False,True]);days['liquidity_rank']=days.groupby('day').cumcount()+1
        days.to_parquet(out/'固定十一币历史日排名.parquet',index=False)
        features=[]
        for r in records:
            g=pd.read_parquet(r['hours_path']);z=indicator(g,start,end);z['symbol']=r['symbol'];features.append(z)
        f=pd.concat(features,ignore_index=True);f['day']=pd.to_datetime(f.decision_hour,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
        m=days[['day','symbol','liquidity_rank']].merge(f,on=['day','symbol'],how='left',validate='one_to_many');assert len(m)==24*len(days)
        m['valid_feature']=np.isfinite(m.score)&np.isfinite(m.rvol);m['valid_count']=m.groupby('decision_hour').valid_feature.transform('sum')
        complete=m[m.valid_count.eq(11)];eligible=complete[complete.valid_feature&complete.rvol.ge(1.5)&complete.score.ne(0)].copy()
        eligible['side']=np.where(eligible.score>0,1,-1);eligible['strength']=eligible.score.abs()
        eligible=eligible.sort_values(['decision_hour','side','strength','liquidity_rank','symbol'],ascending=[True,True,False,True,True])
        eligible['hourly_rank']=eligible.groupby(['decision_hour','side']).cumcount()+1;top=eligible[eligible.hourly_rank<=3]
        top.to_parquet(out/'固定十一币已知小时排名.parquet',index=False)
        events=[pd.read_parquet(r['events_path']) for r in records];events=[x for x in events if len(x)]
        raw=pd.concat(events,ignore_index=True);assert raw.observation_id.is_unique
        raw=raw[raw.quarter_end+M<=ms(end)].copy();raw.to_parquet(out/'固定十一币潜在分钟候选.parquet',index=False)
        market=pd.concat([pd.read_parquet(r['market_path']) for r in records if r['market_path']],ignore_index=True)
        assert not market.duplicated(['symbol','open_time']).any();market.to_parquet(out/'BTC_ETH一分钟合成十五分钟.parquet',index=False)
        calendar_days=(pd.Timestamp(end)-pd.Timestamp(begin)).days
        summary={'year':year,'symbols':len(SYMBOLS),'calendar_days':calendar_days,'days_all_11_liquidity_histories':int(days.day.nunique()),
                 'possible_hours':calendar_days*24,'rankable_hours':int(complete.decision_hour.nunique()),
                 'potential_first_touch_minutes_before_hour_and_dual_filters':len(raw),'raw_events_by_cohort':raw.cohort.value_counts().to_dict(),
                 'source_fp':fp,'note':'Fixed surviving 11 coins; minute touches are not orders or profits.'}
        (out/'候选准备质量.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');summaries.append(summary)
        print('FIXED11_46_CHUNKED_PREPARED',json.dumps(summary,ensure_ascii=False),flush=True)
    (HERE/'固定十一币跨期准备质量.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
