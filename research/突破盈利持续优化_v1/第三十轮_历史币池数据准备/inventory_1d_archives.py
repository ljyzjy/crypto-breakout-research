"""Enumerate public S3 symbol prefixes and 1d file metadata, not trading results."""
import concurrent.futures,hashlib,json,shutil,threading,time,xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd,requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
WORK=ROOT/'work'/'point_in_time_universe30'/'index';WORK.mkdir(parents=True,exist_ok=True)
BASE='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision'
PREFIX='data/futures/um/monthly/klines/'
NS={'s':'http://s3.amazonaws.com/doc/2006-03-01/'};local=threading.local()
MONTHS=['2023-12']+[f'2024-{i:02}' for i in range(1,7)]+[f'2026-{i:02}' for i in range(4,8)]
def session():
    if not hasattr(local,'session'):local.session=requests.Session()
    return local.session
def pages(prefix,delimiter=None):
    token=None
    while True:
        params={'list-type':'2','prefix':prefix,'max-keys':'1000'}
        if delimiter:params['delimiter']=delimiter
        if token:params['continuation-token']=token
        response=session().get(BASE,params=params,timeout=(15,50));response.raise_for_status()
        root=ET.fromstring(response.content);yield root
        if root.findtext('s:IsTruncated',namespaces=NS)!='true':break
        token=root.findtext('s:NextContinuationToken',namespaces=NS)
        if not token:raise RuntimeError('truncated_without_continuation')
def collect_root():
    names=[]
    for root in pages(PREFIX,delimiter='/'):
        names.extend(x.findtext('s:Prefix',namespaces=NS)[len(PREFIX):].rstrip('/') for x in root.findall('s:CommonPrefixes',NS))
    assert len(names)==len(set(names));return sorted(names)
def collect_symbol(symbol):
    fingerprint=hashlib.sha256((symbol+'|'+','.join(MONTHS)+'|'+Path(__file__).read_text(encoding='utf-8')).encode()).hexdigest()
    path=WORK/(fingerprint+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<1_900_000_000:raise RuntimeError('disk_reserve')
        objects=[];base=f'{PREFIX}{symbol}/1d/'
        for root in pages(base):
            for e in root.findall('s:Contents',NS):
                key=e.findtext('s:Key',namespaces=NS)
                for month in MONTHS:
                    if key==f'{base}{symbol}-1d-{month}.zip':
                        objects.append({'symbol':symbol,'month':month,'key':key,'size':int(e.findtext('s:Size',namespaces=NS)),
                                        'last_modified':e.findtext('s:LastModified',namespaces=NS)})
        result={'symbol':symbol,'status':'ok','objects':objects}
        tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
        return result
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:140]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'symbol':symbol,'status':'error','error':error,'objects':[]}
def main():
    symbols=collect_root();candidates=[x for x in symbols if x.endswith('USDT') and '_' not in x]
    print('UNIVERSE30_INDEX_SYMBOLS',len(symbols),'USDT_CANDIDATES',len(candidates),flush=True)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(collect_symbol,x) for x in candidates]
        for fut in concurrent.futures.as_completed(fs):
            results.append(fut.result())
            if len(results)%100==0:print('UNIVERSE30_INDEXED',len(results),'/',len(candidates),flush=True)
    objects=[o for r in results for o in r['objects']]
    df=pd.DataFrame(objects,columns=['symbol','month','key','size','last_modified'])
    if len(df):assert not df.duplicated(['symbol','month']).any()
    df.to_parquet(HERE/'历史日线月档索引.parquet',index=False)
    errors=[{'symbol':r['symbol'],'error':r['error']} for r in results if r['status']!='ok']
    out={'root_symbol_prefixes':len(symbols),'usdt_name_candidates':len(candidates),'symbols_checked':len(results),
         'symbol_errors':errors,'month_counts':df.groupby('month').symbol.nunique().to_dict(),
         'archive_count':len(df),'candidate_name_rule':'ends USDT and no underscore; not proven perpetual',
         'source':'Binance public S3 listing; index files may be missing or changed',
         'plan_sha256':hashlib.sha256((HERE/'数据准备规则.json').read_bytes()).hexdigest(),
         'note':'Availability alone is not contemporaneous exchange status, complete listing history, or financial performance.'}
    (HERE/'历史日线索引清点.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE30_INDEX_COMPLETE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
