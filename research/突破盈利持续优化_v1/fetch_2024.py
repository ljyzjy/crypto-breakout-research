"""Download and validate only public Binance archives for the frozen 2024 check."""
import concurrent.futures
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

import requests

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent/'work'/'breakout_2024_11'
RAW=ROOT/'raw';RAW.mkdir(parents=True,exist_ok=True)
CONTRACTS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
BASE='https://data.binance.vision/data/futures/um/monthly'
local=threading.local()
def get_session():
    if not hasattr(local,'session'):local.session=requests.Session()
    return local.session
def fetch(task):
    kind,contract,month=task
    sub=f'{kind}/{contract}'+('/1m' if kind!='fundingRate' else '')
    suffix='fundingRate' if kind=='fundingRate' else '1m'
    name=f'{contract}-{suffix}-{month}.zip';url=f'{BASE}/{sub}/{name}'
    target=RAW/kind/contract/name;target.parent.mkdir(parents=True,exist_ok=True)
    err='unknown'
    for attempt in range(3):
        try:
            if shutil.disk_usage(ROOT).free<1_200_000_000:raise RuntimeError('insufficient_free_disk')
            checksum=get_session().get(url+'.CHECKSUM',timeout=(12,45))
            if checksum.status_code==404:return {'kind':kind,'contract':contract,'month':month,'status':'missing_checksum_404'}
            checksum.raise_for_status();expected=checksum.text.strip().split()[0].lower()
            if len(expected)!=64:raise ValueError('invalid_checksum')
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:
                return {'kind':kind,'contract':contract,'month':month,'status':'verified_cached','sha256':expected,'bytes':target.stat().st_size}
            response=get_session().get(url,timeout=(12,90));response.raise_for_status();body=response.content
            if hashlib.sha256(body).hexdigest()!=expected:raise ValueError('checksum_mismatch')
            tmp=target.with_suffix('.partial');tmp.write_bytes(body);tmp.replace(target)
            return {'kind':kind,'contract':contract,'month':month,'status':'verified','sha256':expected,'bytes':len(body)}
        except Exception as exc:
            err=str(exc) if str(exc)=='insufficient_free_disk' else type(exc).__name__
            if err=='insufficient_free_disk':break
            if attempt<2:time.sleep(.5*(attempt+1))
    return {'kind':kind,'contract':contract,'month':month,'status':'error','error_type':err}
def main():
    months=[f'2024-{m:02}' for m in range(1,13)]
    tasks=[]
    for c in CONTRACTS:
        tasks += [('klines',c,m) for m in ['2023-12',*months]]
        tasks += [(kind,c,m) for kind in ['markPriceKlines','fundingRate'] for m in months]
    out=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures=[executor.submit(fetch,t) for t in tasks]
        for future in concurrent.futures.as_completed(futures):
            out.append(future.result())
            if len(out)%40==0:print('2024_ARCHIVES',len(out),'/',len(tasks),flush=True)
    out.sort(key=lambda r:(r['kind'],r['contract'],r['month']))
    summary={'expected':len(tasks),'verified':sum(x['status'] in ('verified','verified_cached') for x in out),
             'issues':[x for x in out if x['status'] not in ('verified','verified_cached')],
             'bytes':sum(x.get('bytes',0) for x in out),'records':out,
             'source':'https://github.com/binance/binance-public-data'}
    (HERE/'2024公开档案校验清单.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('2024_DOWNLOAD_COMPLETE',summary['verified'],'/',summary['expected'],'issues',len(summary['issues']),
          'bytes',summary['bytes'],'free_bytes',shutil.disk_usage(ROOT).free,flush=True)
if __name__=='__main__':main()
