"""Fill hourly data for newly ranked top-40 names and calculate causal replacements."""
import concurrent.futures,importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
MINUTE=PARENT/'第三十二轮_历史动态池分钟信号';sys.path.insert(0,str(MINUTE))
from prepare_minute_candidates import task as minute_task
spec=importlib.util.spec_from_file_location('hourly_features_for_backup',PARENT/'第三十一轮_历史动态池小时数据'/'prepare_hourly.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
def main():
    old=pd.read_parquet(PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet')
    daily=pd.read_parquet(HERE/'历史前40候选_仅事前日成交额.parquet')
    oldpairs={(int(r.year),r.symbol) for r in old.itertuples(index=False)}
    newpairs={(int(r.year),r.symbol) for r in daily.itertuples(index=False)}-oldpairs
    print('UNIVERSE34_NEW_SYMBOL_HOURS',len(newpairs),flush=True);results=[]
    # Empty membership produces hourly data only. These year/symbol pairs were
    # absent from the earlier top-20 dataset, so no old candidate cache can collide.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fs=[pool.submit(minute_task,(symbol,year,[])) for year,symbol in sorted(newpairs)]
        for f in concurrent.futures.as_completed(fs):
            try:results.append(f.result())
            except Exception as exc:results.append({'status':'error','error':type(exc).__name__+':'+str(exc)[:140]})
            if len(results)%10==0:print('UNIVERSE34_HOURLY_SYMBOLS',len(results),'/',len(newpairs),flush=True)
    errors=[r for r in results if r['status']!='verified']
    if errors:
        (HERE/'补位小时数据未完成.json').write_text(json.dumps({'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        print('UNIVERSE34_INCOMPLETE',json.dumps(errors,ensure_ascii=False),flush=True);return
    old_hours=pd.read_parquet(MINUTE/'一分钟严格合成小时.parquet')
    new_hours=[pd.read_parquet(r['hour_path']) for r in results]
    all_hours=pd.concat([old_hours,*new_hours],ignore_index=True)
    assert not all_hours.duplicated(['symbol','year','open_time']).any()
    all_hours.to_parquet(HERE/'前40分钟严格合成小时.parquet',index=False)
    features=[]
    for (year,symbol),g in all_hours.groupby(['year','symbol']):
        start,end=('2023-12-01','2024-07-01') if year==2024 else ('2026-04-01','2026-08-01')
        z=module.indicators(g,start,end);z['year']=int(year);z['symbol']=symbol;features.append(z)
    f=pd.concat(features,ignore_index=True);f['day']=pd.to_datetime(f.decision_hour,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    merged=daily[['year','day','symbol','rank']].merge(f,on=['year','day','symbol'],how='left',validate='one_to_many')
    assert len(merged)==24*len(daily)
    available=merged[np.isfinite(merged.score)&np.isfinite(merged.rvol)].sort_values(['decision_hour','rank','symbol']).copy()
    available['eligible_pool_rank']=available.groupby('decision_hour').cumcount()+1
    pool=available[available.eligible_pool_rank<=20].copy()
    pool['pool_size']=pool.groupby('decision_hour').symbol.transform('size');pool=pool[pool.pool_size.eq(20)].copy()
    eligible=pool[pool.rvol.ge(1.5)&pool.score.ne(0)].copy();eligible['side']=np.where(eligible.score>0,1,-1)
    eligible['strength']=eligible.score.abs()
    eligible=eligible.sort_values(['decision_hour','side','strength','rank','symbol'],ascending=[True,True,False,True,True])
    eligible['hourly_rank']=eligible.groupby(['decision_hour','side']).cumcount()+1
    top=eligible[eligible.hourly_rank<=3].copy()
    top.to_parquet(HERE/'逐小时动态替补排名_待候选验证.parquet',index=False)
    coverage=[]
    for year,g in merged.groupby('year'):
        all_times=int(g.decision_hour.nunique());ready=int(pool[pool.year.eq(year)].decision_hour.nunique())
        coverage.append({'year':int(year),'hours':all_times,'hours_with_20_available':ready,
                         'coverage_pct':float(100*ready/all_times) if all_times else None,
                         'provisional_rank_rows':int(top.year.eq(year).sum())})
    status={}
    for r in results:
        for a in r['archives']:status[a['status']]=status.get(a['status'],0)+1
    out={'new_symbol_year_pairs':len(newpairs),'new_archive_status':status,'periods':coverage,
         'note':'Causal data-feed-availability replacement only. Missing archives and product identity remain limitations; no signals or performance have been estimated.'}
    (HERE/'动态替补小时覆盖.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    (HERE/'新增备选小时来源.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_COVERAGE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
