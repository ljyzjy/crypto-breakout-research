"""Fetch public Nov 1–12 minute archives and official funding rates; no credentials."""
import concurrent.futures,hashlib,io,json,threading,time,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent/'work'/'breakout_november_2026'
RAW=ROOT/'raw';OUT=ROOT/'normalized';RAW.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
OLD=HERE.parent.parent/'work'/'breakout_forward_2026'/'normalized'
PRIOR=HERE.parent/'突破胜率与净收益前瞻检验_v1'
pool=json.loads((PRIOR/'冻结研究方案.json').read_text(encoding='utf-8'))['fixed_pool']
local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s

def fetch_archive(task):
    kind,c,day=task;filename=f'{c}-1m-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/{kind}/{c}/1m/{filename}'
    for attempt in range(3):
      try:
        h=session().get(url+'.CHECKSUM',timeout=(12,35))
        if h.status_code==404:return {'kind':kind,'contract':c,'day':day,'status':'missing_checksum_404'}
        h.raise_for_status();expected=h.text.strip().split()[0].lower()
        if len(expected)!=64:raise ValueError('invalid_checksum')
        r=session().get(url,timeout=(12,60));r.raise_for_status();body=r.content
        if hashlib.sha256(body).hexdigest()!=expected:raise ValueError('checksum_mismatch')
        p=RAW/kind/c/filename;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
        return {'kind':kind,'contract':c,'day':day,'status':'verified','sha256':expected,'bytes':len(body)}
      except Exception as e:
        err=type(e).__name__
        if attempt<2:time.sleep(attempt+1)
    return {'kind':kind,'contract':c,'day':day,'status':'error','error_type':err}

def fetch_funding(item):
    c=item['contract'];start=int(pd.Timestamp('2026-10-28',tz='UTC').timestamp()*1000)
    end=int(pd.Timestamp('2026-11-13 08:00',tz='UTC').timestamp()*1000)
    for attempt in range(3):
      try:
        r=session().get('https://www.binance.com/fapi/v1/fundingRate',
            params={'symbol':c,'startTime':start,'endTime':end,'limit':1000},timeout=(12,40))
        r.raise_for_status();x=r.json()
        if not isinstance(x,list) or not x:raise ValueError('empty_funding_history')
        if any(row.get('symbol')!=c for row in x):raise ValueError('funding_symbol_mismatch')
        body=json.dumps(x,sort_keys=True,separators=(',',':')).encode();p=RAW/'fundingRate'/f'{c}.json'
        df=pd.DataFrame(x);ts=pd.to_numeric(df.fundingTime,errors='raise').to_numpy(np.int64)
        if len(set(ts))!=len(ts) or not np.all(np.diff(ts)>0):raise ValueError('funding_time_invalid')
        gaps=np.diff(ts)/3_600_000
        if len(gaps) and (gaps>8.01).any():raise ValueError('funding_gap_above_eight_hours')
        if ts[0]>int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000) or ts[-1]<int(pd.Timestamp('2026-11-12',tz='UTC').timestamp()*1000):raise ValueError('funding_boundary_missing')
        p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
        return {'contract':c,'status':'verified_official_api','rows':len(x),'max_gap_hours':float(gaps.max()) if len(gaps) else None,'sha256':hashlib.sha256(body).hexdigest()}
      except Exception as e:
        err=type(e).__name__
        if attempt<2:time.sleep(attempt+1)
    return {'contract':c,'status':'error','error_type':err}

def parse_zip(path,kind,day):
    d=pd.read_csv(path,compression='zip')
    cols=['open_time','open','high','low','close']
    if kind=='klines':cols+=['volume','quote_volume','count','taker_buy_quote_volume']
    if not set(cols)<=set(d.columns):raise ValueError('unrecognized_daily_schema')
    d=d[cols].rename(columns={'open_time':'ts','count':'trade_count'})
    for c in d.columns:d[c]=pd.to_numeric(d[c],errors='raise')
    d.ts=d.ts.astype('int64');start=int(pd.Timestamp(day,tz='UTC').timestamp()*1000)
    if d.ts.duplicated().any() or not d.ts.between(start,start+86_400_000-1).all() or (d.ts%60_000!=0).any():raise ValueError('invalid_daily_timestamps')
    return d

def main():
    tasks=[(kind,item['contract'],f'2026-11-{day:02}') for item in pool for day in range(1,13) for kind in ['klines','markPriceKlines']]
    records=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futures=[ex.submit(fetch_archive,t) for t in tasks]+[ex.submit(fetch_funding,item) for item in pool]
        for f in concurrent.futures.as_completed(futures):
            records.append(f.result())
            if len(records)%60==0:print('NOV_DATA',len(records),'/',len(futures),flush=True)
    archive=[x for x in records if 'kind' in x];fund=[x for x in records if 'kind' not in x]
    index={(r['kind'],r['contract'],r['day']):r for r in archive}
    fund_status={r['contract']:r['status'] for r in fund}
    novstart=int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000)
    coverage=[]
    for item in pool:
        c=item['contract']
        for kind in ['klines','markPriceKlines']:
            frames=[pd.read_parquet(OLD/f'{c}_{kind}.parquet')]
            for day in range(1,13):
                tag=f'2026-11-{day:02}';rec=index[(kind,c,tag)]
                if rec['status']!='verified':coverage.append({'contract':c,'kind':kind,'day':tag,'rows':0,'status':rec['status']});continue
                p=RAW/kind/c/f'{c}-1m-{tag}.zip';d=parse_zip(p,kind,tag)
                coverage.append({'contract':c,'kind':kind,'day':tag,'rows':len(d),'status':'complete' if len(d)==1440 else 'partial'})
                frames.append(d)
            all_data=pd.concat(frames,ignore_index=True).sort_values('ts')
            if all_data.ts.duplicated().any():raise ValueError('duplicate_extended_data')
            all_data.to_parquet(OUT/f'{c}_{kind}.parquet',index=False)
        prior_fund=pd.read_parquet(OLD/f'{c}_fundingRate.parquet')
        src=RAW/'fundingRate'/f'{c}.json'
        if src.is_file() and fund_status.get(c)=='verified_official_api':
            data=pd.DataFrame(json.loads(src.read_text(encoding='utf-8')))
            data=data.rename(columns={'fundingTime':'ts','fundingRate':'last_funding_rate'})
            data['ts']=pd.to_numeric(data.ts,errors='raise').astype('int64')
            data['last_funding_rate']=pd.to_numeric(data.last_funding_rate,errors='raise')
            data['funding_interval_hours']=8.0
            data=data[data.ts.ge(novstart)][['ts','funding_interval_hours','last_funding_rate']]
            prior_fund=pd.concat([prior_fund,data],ignore_index=True).sort_values('ts')
        if prior_fund.ts.duplicated().any():raise ValueError('duplicate_funding')
        prior_fund.to_parquet(OUT/f'{c}_fundingRate.parquet',index=False)
        print('NOV_NORMALIZED',c,flush=True)
    pd.DataFrame(coverage).to_csv(HERE/'新期间分钟覆盖.csv',index=False,encoding='utf-8-sig')
    report={'archive_expected':len(tasks),'archive_verified':sum(r['status']=='verified' for r in archive),
            'funding_expected':len(pool),'funding_verified':sum(r['status']=='verified_official_api' for r in fund),
            'noncomplete_minutes':[r for r in coverage if r['status']!='complete'],
            'funding_errors':[r for r in fund if r['status']!='verified_official_api'],
            'archive_records':archive,'funding_records':fund,
            'note':'Funding interval 8h is a conservative coverage bound; settlement timestamps and signed rates come from the official API. 4h actual settlements remain recorded individually.'}
    (HERE/'新期间数据与校验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('NOV_DATA_READY',report['archive_verified'],'/',report['archive_expected'],'funding',report['funding_verified'],'/',len(pool),'gaps',len(report['noncomplete_minutes']),flush=True)
if __name__=='__main__':main()
