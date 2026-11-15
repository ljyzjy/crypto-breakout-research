"""Extend coverage for new causal choices; preserve all old snapshots byte-for-byte."""
import json,hashlib,zipfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import pandas as pd
import numpy as np
import pool_engine as p
from download_pool import fetch
ROOT,OLD=p.ROOT,p.OLD

def one(s,tf,month):
    name=f'{s}-{tf}-{month}.zip';old=OLD/'archive-execution'/name
    path=old if old.exists() else ROOT/'archives'/name;path.parent.mkdir(exist_ok=True)
    check=path.with_suffix('.sha256');url=f'https://data.binance.vision/data/spot/monthly/klines/{s}/{tf}/{name}'
    expected=check.read_text() if check.exists() else fetch(url+'.CHECKSUM').decode().split()[0]
    blob=path.read_bytes() if path.exists() else fetch(url);sha=hashlib.sha256(blob).hexdigest();assert sha==expected
    if not path.exists():path.write_bytes(blob)
    if not check.exists():check.write_text(sha)
    return {'symbol':s,'tf':tf,'file':str(path.relative_to(ROOT.parent)),'sha256':sha,'url':url}

def main():
    plan=set()
    for rows in (p.old.rankings()[1],p.slow_rankings()):
        for r in rows:
            for s in r['daily_top2']:
                if s in p.old.base.SYMBOLS:continue
                for offset in range(9):
                    day=pd.Timestamp(r['date'])+pd.Timedelta(days=offset)
                    if day<=pd.Timestamp('2026-10-31'):
                        for tf in ('1h','5m'):plan.add((s,tf,day.strftime('%Y-%m')))
    p.old.base.dump(ROOT/'execution-plan.json',sorted(plan))
    print('Execution coverage plan',len(plan),'archives;',len({s for s,tf,m in plan}),'non-core symbols',flush=True)
    records=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        for i,f in enumerate(as_completed([pool.submit(one,*v) for v in sorted(plan)]),1):
            records.append(f.result())
            if i%50==0:print('Verified',i,'/',len(plan),flush=True)
    parts={}
    for r in records:
        path=ROOT.parent/r['file']
        with zipfile.ZipFile(path) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None)
        x=d.iloc[:,[0,1,2,3,4,5,7,8,10]].copy();x.columns=['date','open','high','low','close','volume','quote_volume','trades','buy_quote']
        x['date']=pd.to_datetime(x.date.where(x.date<10**14,x.date//1000),unit='ms',utc=True).dt.as_unit('us')
        assert x.date.dt.strftime('%Y-%m').eq(path.name[-11:-4]).all()
        parts.setdefault((r['symbol'],r['tf']),[]).append(x)
    manifest={'files':records,'processed':{},'old_hashes':{},'old_rows_unchanged':[]}
    target=ROOT/'execution-data';target.mkdir(exist_ok=True)
    for (s,tf),chunks in parts.items():
        oldpath=OLD/'execution'/f'{s}-{tf}.parquet';oldframe=None
        if oldpath.exists():
            oldframe=p.old.execution_data(s,tf);chunks.append(oldframe.reset_index().rename(columns={'index':'date'}))
            manifest['old_hashes'][str(oldpath.relative_to(OLD))]=hashlib.sha256(oldpath.read_bytes()).hexdigest()
        d=pd.concat(chunks).drop_duplicates().sort_values('date').set_index('date');assert not d.index.duplicated().any(),s
        assert (d[['open','high','low','close']]>0).all().all()
        if oldframe is not None:
            assert np.array_equal(d.loc[oldframe.index,oldframe.columns].to_numpy(),oldframe.to_numpy()),s
            manifest['old_rows_unchanged'].append(f'{s}-{tf}')
        path=target/f'{s}-{tf}.parquet';d.to_parquet(path);manifest['processed'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('pool-daily.parquet','pool-data-manifest.json','automatic-protocol-v2.json','automatic_engine.py','execution-manifest.json'):
        manifest['old_hashes'][name]=hashlib.sha256((OLD/name).read_bytes()).hexdigest()
    p.old.base.dump(ROOT/'execution-data-manifest.json',manifest)
    print('Ready',len(manifest['processed']),'data files; old snapshots unchanged',flush=True)
if __name__=='__main__':main()
