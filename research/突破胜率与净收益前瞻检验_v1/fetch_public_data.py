"""Fetch only Binance public monthly archives with published checksums."""
import concurrent.futures,hashlib,json,threading,time
from pathlib import Path
import requests

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_forward_2026'
PLAN=json.loads((HERE/'冻结研究方案.json').read_text(encoding='utf-8'))
BASE='https://data.binance.vision/data/futures/um/monthly'
local=threading.local()

def session():
    if not hasattr(local,'session'):local.session=requests.Session()
    return local.session

def fetch(spec):
    kind,contract,month=spec
    folder=f'{kind}/{contract}'+('/1m' if kind!='fundingRate' else '')
    suffix='fundingRate' if kind=='fundingRate' else '1m'
    fname=f'{contract}-{suffix}-{month}.zip'
    url=f'{BASE}/{folder}/{fname}'
    target=WORK/kind/contract/fname; target.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(3):
        try:
            check=session().get(url+'.CHECKSUM',timeout=(12,45))
            if check.status_code==404:return {'kind':kind,'contract':contract,'month':month,'status':'missing_checksum_404'}
            if check.status_code!=200:raise RuntimeError('checksum_http_'+str(check.status_code))
            expected=check.text.strip().split()[0].lower()
            if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):raise ValueError('invalid_checksum')
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:
                return {'kind':kind,'contract':contract,'month':month,'status':'verified_cached','sha256':expected,'bytes':target.stat().st_size}
            r=session().get(url,timeout=(12,90))
            if r.status_code==404:return {'kind':kind,'contract':contract,'month':month,'status':'missing_zip_404'}
            if r.status_code!=200:raise RuntimeError('zip_http_'+str(r.status_code))
            data=r.content; actual=hashlib.sha256(data).hexdigest()
            if actual!=expected:raise ValueError('checksum_mismatch')
            tmp=target.with_suffix('.partial');tmp.write_bytes(data);tmp.replace(target)
            return {'kind':kind,'contract':contract,'month':month,'status':'verified','sha256':actual,'bytes':len(data)}
        except Exception as exc:
            error=type(exc).__name__
            if attempt<2:time.sleep(.5*(attempt+1))
    return {'kind':kind,'contract':contract,'month':month,'status':'error','error_type':error}

def main():
    contracts=[r['contract'] for r in PLAN['fixed_pool']]
    tasks=[]
    for c in contracts:
        tasks.extend(('klines',c,f'2026-{m:02}') for m in range(4,11))
        for k in ['markPriceKlines','fundingRate']:
            tasks.extend((k,c,f'2026-{m:02}') for m in range(5,11))
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures=[pool.submit(fetch,t) for t in tasks]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            if len(results)%30==0:print('ARCHIVES',len(results),'/',len(tasks),flush=True)
    results.sort(key=lambda x:(x['kind'],x['contract'],x['month']))
    summary={'expected':len(tasks),'verified':sum(r['status'] in ('verified','verified_cached') for r in results),
             'missing_or_error':[r for r in results if r['status'] not in ('verified','verified_cached')],
             'total_bytes':sum(r.get('bytes',0) for r in results),'records':results,
             'source':'https://github.com/binance/binance-public-data'}
    (HERE/'公开数据校验清单.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DATA_READY',summary['verified'],'/',summary['expected'],'issues',len(summary['missing_or_error']),
          'bytes',summary['total_bytes'],flush=True)

if __name__=='__main__':main()
