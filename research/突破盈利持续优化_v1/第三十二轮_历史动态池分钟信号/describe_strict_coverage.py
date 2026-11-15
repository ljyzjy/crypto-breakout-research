"""Describe strict 20-symbol minute-feature coverage by period, no return tuning."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
spec=importlib.util.spec_from_file_location('coverage_indicators',PARENT/'第三十一轮_历史动态池小时数据'/'prepare_hourly.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
def main():
    daily=pd.read_parquet(PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet')
    hours=pd.read_parquet(HERE/'一分钟严格合成小时.parquet');features=[]
    for (year,symbol),g in hours.groupby(['year','symbol']):
        start,end=('2023-12-01','2024-07-01') if year==2024 else ('2026-04-01','2026-08-01')
        z=module.indicators(g,start,end);z['year']=int(year);z['symbol']=symbol;features.append(z)
    f=pd.concat(features,ignore_index=True);f['day']=pd.to_datetime(f.decision_hour,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    merged=daily[['year','day','symbol']].merge(f,on=['year','day','symbol'],how='left',validate='one_to_many')
    merged['ready']=np.isfinite(merged.score)&np.isfinite(merged.rvol)
    complete=merged.groupby(['year','decision_hour']).ready.sum().rename('ready_count').reset_index()
    events=pd.read_parquet(HERE/'历史动态池潜在触价_待逐笔验证.parquet');result=[]
    for year,g in complete.groupby('year'):
        missing=merged[merged.year.eq(year)&~merged.ready].groupby('symbol').size().sort_values(ascending=False)
        result.append({'year':int(year),'total_hours':len(g),'all20_ready_hours':int(g.ready_count.eq(20).sum()),
                       'all20_ready_pct':float(100*g.ready_count.eq(20).mean()),
                       'potential_touches':int(events.source_year.eq(str(year)).sum()),
                       'most_frequent_missing_feature_symbols':[{'symbol':s,'candidate_hours':int(n)} for s,n in missing.head(8).items()]})
    out={'periods':result,'note':'A missing indicator can reflect zero/no-trade minutes or archive gaps. This is data coverage, not a discovered trading signal or account result.'}
    (HERE/'严格分钟覆盖分期诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE32_COVERAGE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
