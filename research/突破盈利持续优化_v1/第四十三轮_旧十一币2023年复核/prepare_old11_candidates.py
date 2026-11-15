"""Causal 2023 candidate localization from the existing fixed-11 minute archive."""
import hashlib,importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from minute_features_2023 import derive,M,H,Q
H0=Path(__file__).resolve().parent;P=H0.parent;ROOT=P.parent.parent;WORK=ROOT/'work'/'old11_2023_dual'/'symbols';WORK.mkdir(parents=True,exist_ok=True)
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
DAY=86_400_000;START=int(pd.Timestamp('2022-12-01',tz='UTC').timestamp()*1000);END=int(pd.Timestamp('2024-01-01',tz='UTC').timestamp()*1000)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def hourly_indicator():
    path=P/'第三十一轮_历史动态池小时数据'/'prepare_hourly.py'
    spec=importlib.util.spec_from_file_location('old11_hourly43',path);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    return mod.indicators
def process(symbol,src,fp):
    key=hashlib.sha256((fp+'|'+symbol).encode()).hexdigest();base=WORK/key
    meta=base.with_suffix('.json');hp=base.with_suffix('.hours.parquet');dp=base.with_suffix('.days.parquet');ep=base.with_suffix('.events.parquet');mp=base.with_suffix('.market.parquet')
    if all(x.exists() for x in (meta,hp,dp,ep)) and (symbol not in ('BTCUSDT','ETHUSDT') or mp.exists()):return json.loads(meta.read_text(encoding='utf-8'))
    d=pd.read_parquet(src);cols=['ts','open','high','low','close','volume','quote_volume','trade_count']
    assert set(cols).issubset(d.columns) and not d.ts.duplicated().any()
    assert (d.ts%M==0).all() and d.ts.between(START,END-1).all()
    grid=np.arange(START,END,M,dtype=np.int64);a=np.full((len(grid),7),np.nan)
    ix=((d.ts.to_numpy(np.int64)-START)//M).astype(int);assert len(np.unique(ix))==len(ix)
    a[ix]=d[cols[1:]].to_numpy(float);days=a.reshape(-1,1440,7)
    structural=np.isfinite(days).all(axis=(1,2))&(days[:,:,:4]>0).all(axis=(1,2))&(days[:,:,4:]>=0).all(axis=(1,2))
    quote=days[:,:,5].sum(axis=1);quote=np.where(structural&(quote>0),quote,np.nan)
    dates=pd.to_datetime(grid[::1440],unit='ms',utc=True).strftime('%Y-%m-%d')
    past=pd.Series(quote).shift(1).rolling(30,min_periods=30).sum().to_numpy()
    day=pd.DataFrame({'symbol':symbol,'day':dates,'past_30d_quote':past})
    pool=set(day.loc[day.day.ge('2023-01-01')&day.day.lt('2024-01-01')&np.isfinite(day.past_30d_quote),'day'])
    hour,events,counters=derive(a,grid,symbol,2023,pool)
    hour.to_parquet(hp,index=False);day.to_parquet(dp,index=False);pd.DataFrame(events).to_parquet(ep,index=False)
    if symbol in ('BTCUSDT','ETHUSDT'):
        quarter=a.reshape(-1,15,7);v=np.isfinite(quarter).all(axis=(1,2))&(quarter[:,:,:4]>0).all(axis=(1,2))&(quarter[:,:,4:]>=0).all(axis=(1,2))
        vol=quarter[:,:,4].sum(axis=1);count=quarter[:,:,6].sum(axis=1);v&=(vol>0)&(count>0)
        market=pd.DataFrame({'symbol':symbol,'open_time':grid[::15][v],'open':quarter[:,0,0][v],
          'high':np.nanmax(quarter[:,:,1],axis=1)[v],'low':np.nanmin(quarter[:,:,2],axis=1)[v],
          'close':quarter[:,-1,3][v],'volume':vol[v],'count':count[v].astype(np.int64)})
        market.to_parquet(mp,index=False)
    out={'symbol':symbol,'source_sha256':sha(src),'hours_path':str(hp),'days_path':str(dp),'events_path':str(ep),
         'market_path':str(mp) if symbol in ('BTCUSDT','ETHUSDT') else None,'counters':counters,'fingerprint':fp}
    meta.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return out
def main():
    frozen=json.loads((H0/'来源冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(H0/'冻结研究方案.md')==frozen['plan_sha256']
    for x in frozen['sources'].values():assert sha(Path(x['path']))==x['sha256']
    fp=hashlib.sha256(Path(__file__).read_bytes()+(H0/'来源冻结哈希.json').read_bytes()).hexdigest();results=[]
    for symbol in SYMBOLS:
        src=Path(frozen['sources'][f'{symbol}_klines.parquet']['path']);results.append(process(symbol,src,fp))
        print('OLD11_2023_SYMBOLS',len(results),'/',len(SYMBOLS),flush=True)
    days=pd.concat([pd.read_parquet(x['days_path']) for x in results],ignore_index=True)
    days=days[days.day.ge('2023-01-01')&days.day.lt('2024-01-01')&np.isfinite(days.past_30d_quote)].copy()
    days['eligible_count']=days.groupby('day').symbol.transform('size');days=days[days.eligible_count.eq(11)]
    days=days.sort_values(['day','past_30d_quote','symbol'],ascending=[True,False,True]);days['liquidity_rank']=days.groupby('day').cumcount()+1
    days.to_parquet(H0/'固定十一币历史日排名.parquet',index=False)
    indicator=hourly_indicator();features=[]
    for r in results:
        g=pd.read_parquet(r['hours_path']);z=indicator(g,'2022-12-01','2024-01-01');z['symbol']=r['symbol'];features.append(z)
    f=pd.concat(features,ignore_index=True);f['day']=pd.to_datetime(f.decision_hour,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    m=days[['day','symbol','liquidity_rank']].merge(f,on=['day','symbol'],how='left',validate='one_to_many')
    assert len(m)==24*len(days)
    m['valid_feature']=np.isfinite(m.score)&np.isfinite(m.rvol);m['valid_count']=m.groupby('decision_hour').valid_feature.transform('sum')
    complete=m[m.valid_count.eq(11)];eligible=complete[complete.valid_feature&complete.rvol.ge(1.5)&complete.score.ne(0)].copy()
    eligible['side']=np.where(eligible.score>0,1,-1);eligible['strength']=eligible.score.abs()
    eligible=eligible.sort_values(['decision_hour','side','strength','liquidity_rank','symbol'],ascending=[True,True,False,True,True])
    eligible['hourly_rank']=eligible.groupby(['decision_hour','side']).cumcount()+1;top=eligible[eligible.hourly_rank<=3]
    top.to_parquet(H0/'固定十一币已知小时排名.parquet',index=False)
    events=[pd.read_parquet(r['events_path']) for r in results];events=[x for x in events if len(x)]
    raw=pd.concat(events,ignore_index=True);assert raw.observation_id.is_unique
    raw=raw[raw.quarter_end+60_000<=END].copy();raw.to_parquet(H0/'固定十一币潜在分钟候选.parquet',index=False)
    market=pd.concat([pd.read_parquet(r['market_path']) for r in results if r['market_path']],ignore_index=True)
    assert not market.duplicated(['symbol','open_time']).any();market.to_parquet(H0/'BTC_ETH一分钟合成十五分钟.parquet',index=False)
    summary={'symbols':len(SYMBOLS),'calendar_days':365,'days_all_11_liquidity_histories':int(days.day.nunique()),
             'possible_hours':365*24,'rankable_hours':int(complete.decision_hour.nunique()),
             'potential_first_touch_minutes_before_hour_and_dual_filters':len(raw),
             'raw_events_by_cohort':raw.cohort.value_counts().to_dict(),'counters':{r['symbol']:r['counters'] for r in results},
             'source_fp':fp,'note':'Minute OHLC localizes potential touch only; tick data and BTC/ETH prior-bar filter still required.'}
    (H0/'2023候选准备质量.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_CANDIDATES_PREPARED',json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
