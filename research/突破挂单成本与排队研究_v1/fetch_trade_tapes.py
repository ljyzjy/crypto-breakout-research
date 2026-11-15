"""Verify public daily aggTrade archives and retain only needed signal windows."""
import concurrent.futures,hashlib,json,threading,time,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_maker_tapes_2026'
TAPES=WORK/'tapes';TEMP=WORK/'temporary';TAPES.mkdir(parents=True,exist_ok=True);TEMP.mkdir(parents=True,exist_ok=True)
END=int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000)
DAY=86_400_000
signals=pd.read_parquet(HERE/'计划下单候选.parquet')
windows={}
for s in signals.itertuples(index=False):
    start=int(s.ts)-30_000;end=min(int(s.ts)+63*60_000+5_000,END)
    day=start//DAY*DAY
    while day<end:
        tag=pd.Timestamp(day,unit='ms',tz='UTC').strftime('%Y-%m-%d')
        windows.setdefault((s.contract,tag),[]).append((max(day,start),min(day+DAY,end)))
        day+=DAY
local=threading.local()
def session():
    if not hasattr(local,'session'):local.session=requests.Session()
    return local.session

def fetch(item):
    (contract,day),ranges=item
    filename=f'{contract}-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{filename}'
    tmp=TEMP/f'{contract}_{day}.part.zip'
    result={'contract':contract,'day':day,'ranges':ranges}
    for attempt in range(3):
      try:
        checksum=session().get(url+'.CHECKSUM',timeout=(15,40))
        if checksum.status_code==404:return dict(result,status='missing_checksum_404')
        checksum.raise_for_status();expected=checksum.text.strip().split()[0].lower()
        if len(expected)!=64 or any(ch not in '0123456789abcdef' for ch in expected):raise ValueError('invalid_checksum')
        response=session().get(url,timeout=(15,120),stream=True)
        if response.status_code==404:return dict(result,status='missing_archive_404')
        response.raise_for_status();h=hashlib.sha256();size=0
        with tmp.open('wb') as f:
            for part in response.iter_content(chunk_size=1024*1024):
                if part:f.write(part);h.update(part);size+=len(part)
        if h.hexdigest()!=expected:raise ValueError('checksum_mismatch')
        parts=[];columns=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
        with zipfile.ZipFile(tmp) as z:
            members=[n for n in z.namelist() if n.endswith('.csv')]
            if len(members)!=1:raise ValueError('unexpected_zip_contents')
            with z.open(members[0]) as f:
                for chunk in pd.read_csv(f,usecols=columns,chunksize=250_000):
                    t=pd.to_numeric(chunk.transact_time,errors='raise').to_numpy(np.int64)
                    mask=np.zeros(len(chunk),dtype=bool)
                    for lo,hi in ranges:mask|=(t>=lo)&(t<hi)
                    if mask.any():parts.append(chunk.loc[mask,columns])
        if parts:
            d=pd.concat(parts,ignore_index=True)
            d['transact_time']=pd.to_numeric(d.transact_time,errors='raise').astype('int64')
            d['agg_trade_id']=pd.to_numeric(d.agg_trade_id,errors='raise').astype('int64')
            d['price']=pd.to_numeric(d.price,errors='raise');d['quantity']=pd.to_numeric(d.quantity,errors='raise')
            if d.agg_trade_id.duplicated().any() or not np.isfinite(d[['price','quantity']]).all().all() or (d[['price','quantity']]<=0).any().any():raise ValueError('invalid_trade_records')
            if not pd.api.types.is_bool_dtype(d.is_buyer_maker):
                vals=d.is_buyer_maker.astype(str).str.lower()
                if not vals.isin(['true','false']).all():raise ValueError('unknown_aggressor_flag')
                d['is_buyer_maker']=vals.eq('true')
            d=d.sort_values(['transact_time','agg_trade_id']).reset_index(drop=True)
        else:d=pd.DataFrame({'agg_trade_id':pd.Series(dtype='int64'),'price':pd.Series(dtype='float64'),
                'quantity':pd.Series(dtype='float64'),'transact_time':pd.Series(dtype='int64'),
                'is_buyer_maker':pd.Series(dtype='bool')})
        target=TAPES/f'{contract}_{day}.parquet';d.to_parquet(target,index=False)
        if not tmp.resolve().is_relative_to(TEMP.resolve()) or not tmp.name.endswith('.part.zip'):raise ValueError('invalid_temporary_path')
        tmp.unlink()
        return dict(result,status='verified',archive_sha256=expected,archive_bytes=size,retained_rows=len(d),
                    retained_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
      except Exception as exc:
        error=type(exc).__name__
        if attempt<2:time.sleep(attempt+1)
    return dict(result,status='error',error_type=error)

def main():
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for f in concurrent.futures.as_completed([pool.submit(fetch,item) for item in windows.items()]):
            results.append(f.result())
            if len(results)%10==0:print('TAPES',len(results),'/',len(windows),flush=True)
    results.sort(key=lambda x:(x['contract'],x['day']))
    report={'candidate_orders':len(signals),'required_contract_days':len(windows),
       'verified':sum(r['status']=='verified' for r in results),
       'missing_or_error':[r for r in results if r['status']!='verified'],
       'downloaded_bytes':sum(r.get('archive_bytes',0) for r in results),'records':results,
       'source':'https://github.com/binance/binance-public-data',
       'archive_policy':'Verified archives are removed from task-owned temporary directory after extraction; checksums and relevant trade windows are retained.'}
    (HERE/'逐笔成交数据校验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TAPES_READY',report['verified'],'/',report['required_contract_days'],'issues',len(report['missing_or_error']),'bytes',report['downloaded_bytes'],flush=True)
if __name__=='__main__':main()
