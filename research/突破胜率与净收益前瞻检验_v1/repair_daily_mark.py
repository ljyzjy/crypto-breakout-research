"""Fill the identified monthly mark-price archive gap from verified official daily files."""
import concurrent.futures,hashlib,json,time
from pathlib import Path
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_forward_2026'
OUT=WORK/'normalized'
plan=json.loads((HERE/'冻结研究方案.json').read_text(encoding='utf-8'))
day='2026-06-29'
start=int(pd.Timestamp(day,tz='UTC').timestamp()*1000);end=start+86_400_000

def one(item):
    c=item['contract'];fname=f'{c}-1m-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/markPriceKlines/{c}/1m/{fname}'
    for attempt in range(3):
        try:
            check=requests.get(url+'.CHECKSUM',timeout=(12,30));check.raise_for_status()
            expected=check.text.strip().split()[0].lower()
            response=requests.get(url,timeout=(12,60));response.raise_for_status(); data=response.content
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('checksum_mismatch')
            target=WORK/'markPriceKlines_daily'/c/fname;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            daily=pd.read_csv(target,compression='zip')[['open_time','open','high','low','close']].rename(columns={'open_time':'ts'})
            for col in daily.columns:daily[col]=pd.to_numeric(daily[col],errors='raise')
            daily.ts=daily.ts.astype('int64')
            if len(daily)!=1440 or daily.ts.duplicated().any() or not ((daily.ts>=start)&(daily.ts<end)&(daily.ts%60_000==0)).all():raise ValueError('unexpected_daily_coverage')
            old=pd.read_parquet(OUT/f'{c}_markPriceKlines.parquet')
            existing=old[old.ts.between(start,end-1)].sort_values('ts').reset_index(drop=True)
            if len(existing):
                check_daily=daily.sort_values('ts').reset_index(drop=True)
                if len(existing)!=1440 or not existing.equals(check_daily):raise ValueError('daily_monthly_overlap')
                return {'contract':c,'status':'verified','rows':len(daily),'sha256':expected,'cached':True}
            merged=pd.concat([old,daily],ignore_index=True).sort_values('ts')
            if merged.ts.duplicated().any():raise ValueError('duplicate_after_repair')
            merged.to_parquet(OUT/f'{c}_markPriceKlines.parquet',index=False)
            return {'contract':c,'status':'verified','rows':len(daily),'sha256':expected}
        except Exception as exc:
            err=type(exc).__name__
            if attempt<2:time.sleep(attempt+1)
    return {'contract':c,'status':'failed','error_type':err}

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    results=list(pool.map(one,plan['fixed_pool']))
report={'date':day,'discovery':'All 18 official June monthly mark files lack this entire UTC date.',
        'purpose':'Repair known source coverage before outcome calculations; daily archive and checksum are official.',
        'records':results,'complete':all(r['status']=='verified' for r in results)}
(HERE/'标记价格日档补齐记录.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('MARK_REPAIR',sum(r['status']=='verified' for r in results),'/',len(results),flush=True)
