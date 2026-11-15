"""Public archive data, including symbols that are no longer traded today."""
import concurrent.futures as cf
import hashlib, io, json, time, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
import requests
import pandas as pd

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'data'; CACHE.mkdir(exist_ok=True)
BASE='https://data.binance.vision/data/spot/monthly/klines'
STABLE={'USDC','BUSD','TUSD','USDP','DAI','PAX','UST','USTC','USDD','USDE','FDUSD','USD1','USDS','EUR','AEUR','GBP','AUD','BRL','BIDR','IDRT','VAI','SUSD'}

def fetch(url, missing=False):
    for attempt in range(3):
        try:
            r=requests.get(url,timeout=20)
            if missing and r.status_code==404:return None
            r.raise_for_status();return r.content
        except requests.RequestException:
            if attempt==2:raise
            time.sleep(attempt+1)

def monthly(symbol,month):
    name=f'{symbol}-1d-{month}.zip';path=CACHE/name
    url=f'{BASE}/{symbol}/1d/{name}'
    if path.exists():blob=path.read_bytes()
    else:
        blob=fetch(url,True)
        if blob is None:return None
    check=path.with_suffix('.sha256')
    digest=hashlib.sha256(blob).hexdigest()
    expected=check.read_text() if check.exists() else fetch(url+'.CHECKSUM').decode().split()[0]
    if expected!=digest:raise ValueError('checksum mismatch '+name)
    path.write_bytes(blob);check.write_text(expected)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw=pd.read_csv(z.open(z.namelist()[0]),header=None)
    frame=raw.iloc[:,[0,1,2,3,4,5,7]].copy()
    frame.columns=['date','open','high','low','close','volume','quote_volume']
    frame['date']=pd.to_datetime(frame.date,unit='us' if int(frame.date.iloc[0])>10**14 else 'ms',utc=True)
    return frame

def symbols():
    saved=ROOT/'archive-symbols.json'
    if saved.exists():return json.loads(saved.read_text())
    prefix='data/spot/monthly/klines/';marker=None;found=[]
    ns={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
    while True:
        params={'delimiter':'/','prefix':prefix}
        if marker:params['marker']=marker
        r=requests.get('https://s3-ap-northeast-1.amazonaws.com/data.binance.vision',params=params,timeout=30)
        r.raise_for_status();tree=ET.fromstring(r.content)
        found.extend(e.text.split('/')[-2] for e in tree.findall('s:CommonPrefixes/s:Prefix',ns))
        if tree.find('s:IsTruncated',ns).text=='false':break
        marker=tree.find('s:NextMarker',ns).text
    found=sorted(s for s in found if s.endswith('USDT') and s[:-4] not in STABLE
                 and not any(s[:-4].endswith(x) for x in ('UP','DOWN','BULL','BEAR')))
    saved.write_text(json.dumps(found));return found

def history(symbol,months):
    """Use anonymous klines when complete; archived delisted symbols fall back to ZIPs."""
    target=CACHE/(symbol+'.feather')
    if target.exists():return symbol,pd.read_feather(target)
    start=int(pd.Timestamp('2022-07-01',tz='UTC').timestamp()*1000)
    end=int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000)-1
    rows=[];session=requests.Session()
    try:
        while start<=end:
            r=session.get('https://data-api.binance.vision/api/v3/klines',params={
                'symbol':symbol,'interval':'1d','startTime':start,'endTime':end,'limit':1000},timeout=20)
            r.raise_for_status();part=r.json()
            if not part:break
            rows.extend(part);start=int(part[-1][0])+86400000
        raw=pd.DataFrame(rows)
        if len(raw)<180:raise ValueError('Insufficient API history')
        # A truncated API history must not silently remove a delisted asset's older records.
        if int(raw.iloc[0,0])>int(pd.Timestamp('2022-12-01',tz='UTC').timestamp()*1000):
            raise ValueError('API history starts after fixed formation month')
        d=raw.iloc[:,[0,1,2,3,4,5,7]].copy();d.columns=['date','open','high','low','close','volume','quote_volume']
        d['date']=pd.to_datetime(d.date,unit='ms',utc=True)
        for col in d.columns[1:]:d[col]=d[col].astype(float)
        # API results are snapshotted and hashed; archive checksum validation is separate.
        (CACHE/(symbol+'-source.json')).write_text(json.dumps({'source':'Binance anonymous spot klines',
          'retrieved_at':pd.Timestamp.now(tz='UTC').isoformat(),'rows':len(d)}))
        return symbol,d
    except (requests.RequestException,ValueError,IndexError):
        parts=[]
        for month in months:
            d=monthly(symbol,month)
            if d is not None:parts.append(d)
        (CACHE/(symbol+'-source.json')).write_text(json.dumps({'source':'Binance SHA256-verified monthly archives',
          'retrieved_at':pd.Timestamp.now(tz='UTC').isoformat()}))
        return symbol,pd.concat(parts)

def main():
    frozen=ROOT/'universe.json'
    if not frozen.exists():
        candidates=symbols();rows=[];errors=[]
        print('archive candidate symbols',len(candidates),flush=True)
        with cf.ThreadPoolExecutor(max_workers=12) as pool:
            futures={pool.submit(monthly,s,'2022-12'):s for s in candidates}
            for i,f in enumerate(cf.as_completed(futures),1):
                s=futures[f]
                try:
                    d=f.result()
                    if d is not None and len(d)>=28:
                        rows.append({'symbol':s,'median_quote_volume':float(d.quote_volume.median())})
                except Exception as e:errors.append({'symbol':s,'error':type(e).__name__})
                if i%50==0:print('screen',i,'/',len(candidates),'valid',len(rows),'errors',len(errors),flush=True)
        if errors:
            (ROOT/'screen-errors.json').write_text(json.dumps(errors));raise RuntimeError('Incomplete screening; rerun to use cache and retry errors')
        rows.sort(key=lambda r:(-r['median_quote_volume'],r['symbol']))
        frozen.write_text(json.dumps({'asof':'2022-12-31','method':'December 2022 median daily USDT turnover; 28+ days; top 20, stable/leveraged excluded',
                                     'candidates':rows,'selected':[r['symbol'] for r in rows[:20]]},indent=2))
    chosen=json.loads(frozen.read_text())['selected'];print('chosen',chosen,flush=True)
    months=pd.date_range('2022-07-01','2026-11-01',freq='MS',inclusive='left').strftime('%Y-%m').tolist()
    frames={};errors=[]
    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        futures={pool.submit(history,s,months):s for s in chosen}
        for i,f in enumerate(cf.as_completed(futures),1):
            s=futures[f]
            try:
                symbol,d=f.result();frames[symbol]=d
            except Exception as e:errors.append([s,type(e).__name__])
            print('history',i,'/',len(futures),s,'errors',len(errors),flush=True)
    if errors:
        (ROOT/'history-errors.json').write_text(json.dumps(errors));raise RuntimeError('Incomplete history; rerun')
    for s,d in frames.items():
        d=d.sort_values('date').reset_index(drop=True)
        assert not d.date.duplicated().any(),s
        assert (d[['open','high','low','close']]>0).all().all(),s
        d.to_feather(CACHE/(s+'.feather'))
    print('DATA READY',flush=True)

if __name__=='__main__':main()
