"""Restore one omitted mark-price day only from verified official daily archives."""
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent/'work'/'breakout_2023_11'
NORM=ROOT/'normalized';RAW=ROOT/'daily_mark_repair'
contracts=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
day='2023-02-24';start=int(pd.Timestamp(day,tz='UTC').timestamp()*1000);end=start+86_400_000
def fetch(c):
    name=f'{c}-1m-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/markPriceKlines/{c}/1m/{name}'
    with requests.Session() as session:
        checksum=session.get(url+'.CHECKSUM',timeout=(12,45));checksum.raise_for_status()
        expected=checksum.text.strip().split()[0].lower()
        response=session.get(url,timeout=(12,60));response.raise_for_status();body=response.content
    assert hashlib.sha256(body).hexdigest()==expected
    d=pd.read_csv(io.BytesIO(body),compression='zip')[['open_time','open','high','low','close']].rename(columns={'open_time':'ts'})
    for col in d.columns:d[col]=pd.to_numeric(d[col],errors='raise')
    d.ts=d.ts.astype('int64')
    assert len(d)==1440 and not d.ts.duplicated().any() and d.ts.between(start,end-1).all()
    (RAW/c).mkdir(parents=True,exist_ok=True);(RAW/c/name).write_bytes(body)
    path=NORM/f'{c}_markPriceKlines.parquet';old=pd.read_parquet(path)
    assert not old.ts.between(start,end-1).any()
    out=pd.concat([old,d],ignore_index=True).sort_values('ts').reset_index(drop=True)
    assert not out.ts.duplicated().any() and out.ts.between(start,end-1).sum()==1440
    out.to_parquet(path,index=False)
    return {'contract':c,'day':day,'rows':len(d),'sha256':expected,'status':'verified_added'}
def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,contracts))
    report={'records':results,'repaired_contracts':len(results),'repaired_minutes':len(results)*1440,
            'source':'Binance public verified daily mark-price archives',
            'method':'Only a missing day was added; no interpolation or overwriting monthly observations.'}
    (HERE/'2023日档修复记录.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('2023_DAILY_MARK_REPAIRED',len(results),flush=True)
if __name__=='__main__':main()
