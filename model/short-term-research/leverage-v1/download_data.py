"""Public USDT perpetual archives only; no account endpoints or credentials."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,io,json,time,urllib.request,zipfile
import pandas as pd

ROOT=Path(__file__).resolve().parent
BASE='https://data.binance.vision/data/futures/um/monthly'

def fetch(url):
 for attempt in range(3):
  try:
   with urllib.request.urlopen(url,timeout=25) as r:return r.read()
  except Exception:
   if attempt==2:raise
   time.sleep(1+attempt)

def one(symbol,kind,month):
 name=f'{symbol}-fundingRate-{month}.zip' if kind=='fundingRate' else f'{symbol}-5m-{month}.zip'
 url=f'{BASE}/{kind}/{symbol}/'+('' if kind=='fundingRate' else '5m/')+name
 path=ROOT/'archive'/kind/name;path.parent.mkdir(parents=True,exist_ok=True)
 checksum=path.with_suffix('.zip.CHECKSUM')
 expected=checksum.read_bytes() if checksum.exists() else fetch(url+'.CHECKSUM')
 blob=path.read_bytes() if path.exists() else fetch(url)
 sha=hashlib.sha256(blob).hexdigest();assert sha==expected.decode().split()[0],url
 if not path.exists():path.write_bytes(blob)
 if not checksum.exists():checksum.write_bytes(expected)
 with zipfile.ZipFile(io.BytesIO(blob)) as z:d=pd.read_csv(z.open(z.namelist()[0]))
 return symbol,kind,d,{'file':str(path.relative_to(ROOT)),'sha256':sha,'url':url,'rows':len(d)}

def main():
 months=pd.date_range('2025-01-01','2026-11-01',freq='MS',inclusive='left');parts={};files=[]
 with ThreadPoolExecutor(max_workers=6) as pool:
  jobs=[pool.submit(one,s,k,m.strftime('%Y-%m')) for s in ['BTCUSDT','ETHUSDT'] for k in ['klines','markPriceKlines','fundingRate'] for m in months]
  for i,f in enumerate(as_completed(jobs),1):
   s,k,d,record=f.result();parts.setdefault((s,k),[]).append(d);files.append(record)
   if i%12==0:print(f'Public futures archives verified {i}/{len(jobs)}',flush=True)
 audit=[]
 for (s,k),chunks in parts.items():
  d=pd.concat(chunks);timecol='calc_time' if k=='fundingRate' else 'open_time'
  d=d.sort_values(timecol);assert not d[timecol].duplicated().any()
  if k!='fundingRate':
   expected_times=pd.date_range('2025-01-01','2026-11-01',freq='5min',tz='UTC',inclusive='left')
   actual_times=pd.to_datetime(d[timecol],unit='ms',utc=True)
   missing=expected_times.difference(actual_times)
   for day in sorted(set(missing.strftime('%Y-%m-%d'))):
    name=f'{s}-5m-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/{k}/{s}/5m/{name}'
    path=ROOT/'archive'/k/name;check=path.with_suffix('.zip.CHECKSUM')
    blob=path.read_bytes() if path.exists() else fetch(url)
    expected=check.read_bytes() if check.exists() else fetch(url+'.CHECKSUM')
    sha=hashlib.sha256(blob).hexdigest();assert sha==expected.decode().split()[0]
    path.write_bytes(blob);check.write_bytes(expected)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:daily=pd.read_csv(z.open(z.namelist()[0]))
    extra=daily[~daily[timecol].isin(d[timecol])]
    d=pd.concat([d,extra]).sort_values(timecol)
    files.append({'file':str(path.relative_to(ROOT)),'sha256':sha,'url':url,'rows':len(daily),'missing_monthly_rows_recovered':len(extra)})
    print(f'Recovered {len(extra)} missing monthly {k} rows from verified daily archive: {s} {day}',flush=True)
   assert d[timecol].diff().dropna().eq(300000).all()
   assert len(d)==len(expected_times)
   assert (d[['open','high','low','close']]>0).all().all()
   assert d.high.ge(d[['open','low','close']].max(axis=1)).all() and d.low.le(d[['open','high','close']].min(axis=1)).all()
  else:
   # Recorded settlements contain millisecond jitter; preserve raw and map to scheduled UTC boundary later.
   schedule=pd.to_datetime(d.calc_time,unit='ms',utc=True).dt.round('h')
   assert not schedule.duplicated().any()
   diffs=schedule.diff().dt.total_seconds().iloc[1:]/3600
   assert ((diffs-d.funding_interval_hours.iloc[1:].to_numpy()).abs()<.001).all()
  out=ROOT/'processed'/f'{s}-{k}.parquet';out.parent.mkdir(exist_ok=True);d.reset_index(drop=True).to_parquet(out,index=False)
  audit.append({'symbol':s,'kind':k,'rows':len(d),'first_ms':int(d[timecol].iloc[0]),'last_ms':int(d[timecol].iloc[-1]),'processed':str(out.relative_to(ROOT)),'processed_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'continuous':True})
 (ROOT/'data-manifest.json').write_text(json.dumps({'downloaded_utc':pd.Timestamp.now(tz='UTC').isoformat(),'files':sorted(files,key=lambda x:x['file']),'summary':audit},indent=2),encoding='utf-8')
 print(json.dumps(audit),flush=True)

if __name__=='__main__':main()
