"""Download execution months needed by ex-ante ranks, never by realised returns."""
import json,hashlib,io,zipfile
from concurrent.futures import ThreadPoolExecutor,as_completed
import pandas as pd
import automatic_engine as a
from download_pool import fetch
ROOT=a.ROOT

def one(s,tf,month):
    name=f'{s}-{tf}-{month}.zip';url=f'https://data.binance.vision/data/spot/monthly/klines/{s}/{tf}/{name}'
    p=ROOT/'archive-execution'/name;p.parent.mkdir(exist_ok=True);check=p.with_suffix('.sha256')
    expected=check.read_text() if check.exists() else fetch(url+'.CHECKSUM').decode().split()[0]
    blob=p.read_bytes() if p.exists() else fetch(url);sha=hashlib.sha256(blob).hexdigest();assert sha==expected
    if not p.exists():p.write_bytes(blob)
    if not check.exists():check.write_text(sha)
    return {'symbol':s,'tf':tf,'file':name,'sha256':sha,'url':url}

def main():
    _,trace,excluded=a.rankings();a.base.dump(ROOT/'daily-ranks.json',trace)
    pairs=set()
    for r in trace:
        for s in r['daily_top2']:
            if s in a.base.SYMBOLS:continue
            for offset in range(9):
                day=pd.Timestamp(r['date'])+pd.Timedelta(days=offset)
                if day<=pd.Timestamp('2026-10-31'):pairs.add((s,day.strftime('%Y-%m')))
    plan=sorted((s,tf,m) for s,m in pairs for tf in ('1h','5m'))
    a.base.dump(ROOT/'execution-plan.json',{'plan':plan,'excluded':excluded,'logic':'daily top2 plus8days; covers arbitrary initial date and subsequent weekly holdings including exits'})
    print('Execution plan',len(plan),'monthly archives',len({s for s,m in pairs}),'coins',flush=True)
    records=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        for i,f in enumerate(as_completed([pool.submit(one,*r) for r in plan]),1):
            records.append(f.result())
            if i%40==0:print('Execution verified',i,'/',len(plan),flush=True)
    parts={}
    for r in records:
        with zipfile.ZipFile(ROOT/'archive-execution'/r['file']) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None)
        x=d.iloc[:,[0,1,2,3,4,5,7,8,10]].copy();x.columns=['date','open','high','low','close','volume','quote_volume','trades','buy_quote']
        stamps=x.date.where(x.date<10**14,x.date//1000)
        x['date']=pd.to_datetime(stamps,unit='ms',utc=True).dt.as_unit('us')
        assert x.date.dt.strftime('%Y-%m').eq(r['file'][-11:-4]).all()
        parts.setdefault((r['symbol'],r['tf']),[]).append(x)
    processed={};(ROOT/'execution').mkdir(exist_ok=True)
    for (s,tf),chunks in parts.items():
        d=pd.concat(chunks).sort_values('date').drop_duplicates().set_index('date');assert not d.index.duplicated().any()
        assert (d[['open','high','low','close']]>0).all().all()
        p=ROOT/'execution'/f'{s}-{tf}.parquet';d.to_parquet(p);processed[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    a.base.dump(ROOT/'execution-manifest.json',{'files':records,'processed':processed})
    print('EXECUTION DATA READY',len(processed),flush=True)

if __name__=='__main__':main()
