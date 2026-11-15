"""Enumerate the historical public archive, not today's active exchange symbols."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests,threading,time,hashlib,json,xml.etree.ElementTree as ET,io,zipfile
import pandas as pd
ROOT=Path(__file__).resolve().parent
NS={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
BUCKET='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision'
LOCAL=threading.local()

def fetch(url,params=None):
    if not hasattr(LOCAL,'session'):LOCAL.session=requests.Session()
    for attempt in range(4):
        try:
            r=LOCAL.session.get(url,params=params,timeout=25);r.raise_for_status();return r.content
        except requests.RequestException:
            if attempt==3:raise
            time.sleep(attempt+1)

def listing(prefix,delimiter=None):
    params={'prefix':prefix};out=[]
    if delimiter:params['delimiter']=delimiter
    while True:
        blob=fetch(BUCKET,params);tree=ET.fromstring(blob)
        tag='s:CommonPrefixes/s:Prefix' if delimiter else 's:Contents/s:Key'
        out.extend(e.text for e in tree.findall(tag,NS))
        if tree.find('s:IsTruncated',NS).text=='false':return out
        nxt=tree.find('s:NextMarker',NS)
        params['marker']=nxt.text if nxt is not None else out[-1]

def archive(key):
    name=key.split('/')[-1];path=ROOT/'archive-daily'/name;path.parent.mkdir(parents=True,exist_ok=True)
    url='https://data.binance.vision/'+key;check=path.with_suffix('.sha256')
    expected=check.read_text() if check.exists() else fetch(url+'.CHECKSUM').decode().split()[0]
    blob=path.read_bytes() if path.exists() else fetch(url)
    sha=hashlib.sha256(blob).hexdigest()
    assert sha==expected,name
    if not path.exists():path.write_bytes(blob)
    if not check.exists():check.write_text(sha)
    return {'file':name,'sha256':sha,'url':url}

def symbols():
    p=ROOT/'archive-symbols.json'
    if p.exists():return json.loads(p.read_text())
    values=sorted(x.split('/')[-2] for x in listing('data/spot/monthly/klines/','/') if x.split('/')[-2].endswith('USDT'))
    p.write_text(json.dumps(values),encoding='utf-8');return values

def discover(symbol):
    p=ROOT/'listings'/(symbol+'.json');p.parent.mkdir(exist_ok=True)
    if p.exists():return json.loads(p.read_text())
    keys=[k for k in listing(f'data/spot/monthly/klines/{symbol}/1d/') if k.endswith('.zip') and '2024-09'<=k[-11:-4]<='2026-10']
    p.write_text(json.dumps(keys),encoding='utf-8');return keys

def main():
    syms=symbols();keys=[];print('Historical USDT archive directories',len(syms),flush=True)
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures=[pool.submit(discover,s) for s in syms]
        for i,f in enumerate(as_completed(futures),1):
            keys.extend(f.result())
            if i%100==0:print('Discovered',i,'/',len(syms),'archives',len(keys),flush=True)
    keys.sort();(ROOT/'pool-archive-plan.json').write_text(json.dumps(keys),encoding='utf-8')
    print('Downloading SHA256 verified daily archives',len(keys),flush=True)
    records=[]
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures=[pool.submit(archive,k) for k in keys]
        for i,f in enumerate(as_completed(futures),1):
            records.append(f.result())
            if i%300==0:print('Verified',i,'/',len(keys),flush=True)
    parts={};mixed_units=[]
    for r in records:
        with zipfile.ZipFile(ROOT/'archive-daily'/r['file']) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None)
        if d.empty:continue
        micro=d[0].ge(10**14)
        if micro.any() and not micro.all():mixed_units.append(r['file'])
        x=d.iloc[:,[0,1,2,3,4,5,7]].copy();x.columns=['date','open','high','low','close','volume','quote_volume']
        stamps=x.date.where(~micro,x.date//1000)
        x['date']=pd.to_datetime(stamps,unit='ms',utc=True).dt.as_unit('us');x['symbol']=r['file'].split('-')[0]
        expected_month=r['file'][-11:-4]
        assert x.date.dt.strftime('%Y-%m').eq(expected_month).all(),'Out-of-month daily timestamps: '+r['file']
        parts.setdefault(x.symbol.iloc[0],[]).append(x)
    all_rows=[];audit=[];duplicates=[]
    for s,chunks in parts.items():
        d=pd.concat(chunks).sort_values('date')
        if d.date.duplicated().any():
            n=len(d);d=d.drop_duplicates()
            duplicates.append({'symbol':s,'identical_rows_removed':n-len(d)})
            assert not d.date.duplicated().any(),'Conflicting duplicate daily rows: '+s
        assert (d[['open','high','low','close']]>0).all().all(),s
        assert (d.high>=d[['open','close','low']].max(axis=1)).all(),s
        assert (d.low<=d[['open','close','high']].min(axis=1)).all(),s
        all_rows.append(d);audit.append({'symbol':s,'rows':len(d),'first':d.date.min().isoformat(),'last':d.date.max().isoformat()})
    target=ROOT/'pool-daily.parquet';pd.concat(all_rows).to_parquet(target,index=False)
    manifest={'retrieved_utc':pd.Timestamp.now(tz='UTC').isoformat(),'directory_count':len(syms),'symbols_with_period_data':len(parts),'archives':records,'summary':audit,'identical_duplicates':duplicates,'mixed_unit_archives_normalized_per_row':mixed_units,'pool_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (ROOT/'pool-data-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
    print('POOL READY',len(parts),'symbols',len(records),'verified archives',flush=True)

if __name__=='__main__':main()
