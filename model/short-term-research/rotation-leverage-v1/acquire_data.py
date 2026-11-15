"""Acquire only public historical archives; reuse and never rewrite prior study data."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import sys,json,hashlib,zipfile,io
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parent;RESEARCH=ROOT.parent
sys.path.insert(0,str(RESEARCH/'pool-optimization-v1'));import pool_engine as p
from download_pool import fetch,listing
dump=p.old.base.dump;read=p.old.base.read

def cached_listing(prefix,delimiter=None):
    dest=ROOT/'listings'/(hashlib.sha256((prefix+str(delimiter)).encode()).hexdigest()+'.json');dest.parent.mkdir(exist_ok=True)
    if dest.exists():return read(dest)
    data=listing(prefix,delimiter);dump(dest,data);return data

def archive(key,spot=False):
    url='https://data.binance.vision/'+key;name=key.split('/')[-1]
    path=ROOT/'archives'/('spot' if spot else key.split('/')[4])/name
    candidates=([p.ROOT/'archives'/name,p.OLD/'archive-execution'/name] if spot else [RESEARCH/'leverage-v1/archive'/key.split('/')[4]/name])
    path=next((x for x in candidates if x.exists()),path)
    if path.suffix=='.zip' and path.with_suffix('.sha256').exists():sha_expected=path.with_suffix('.sha256').read_text().strip()
    elif path.with_suffix('.zip.CHECKSUM').exists():sha_expected=path.with_suffix('.zip.CHECKSUM').read_text().split()[0]
    else:sha_expected=fetch(url+'.CHECKSUM').decode().split()[0]
    blob=path.read_bytes() if path.exists() else fetch(url)
    sha=hashlib.sha256(blob).hexdigest();assert sha==sha_expected,key
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob);path.with_suffix('.sha256').write_text(sha)
    return {'key':key,'file':str(path.relative_to(RESEARCH)),'sha256':sha}

def main():
    plans=set()
    for r in p.slow_rankings():
        for s in {q['symbol'] for q in r['ranked'][:4]}|{'BTCUSDT','ETHUSDT'}:
            for offset in range(-1,9):
                d=pd.Timestamp(r['date'])+pd.Timedelta(days=offset)
                if d<=pd.Timestamp('2026-10-31'):plans.add((s,d.strftime('%Y-%m')))
    dump(ROOT/'coverage-plan.json',sorted(plans));syms=sorted({s for s,m in plans})
    dirs=cached_listing('data/futures/um/monthly/klines/','/')
    contracts={s.split('/')[-2] for s in dirs}
    mapping={s:next((c for c in (s,'1000'+s,'1000000'+s) if c in contracts),None) for s in syms}
    dump(ROOT/'contract-map.json',mapping)
    print('Plan',len(syms),'spot assets;',len(plans),'asset-months;',sum(c is None for c in mapping.values()),'without contract',flush=True)
    jobs=[];availability={}
    def discover(s,kind):
        c=mapping[s];prefix=f'data/futures/um/monthly/{kind}/{c}/'+('' if kind=='fundingRate' else '5m/')
        keys=[k for k in cached_listing(prefix) if k.endswith('.zip')]
        requested={m for sym,m in plans if sym==s}
        return s,kind,keys,[k for k in keys if k[-11:-4] in requested]
    with ThreadPoolExecutor(max_workers=12) as pool:
        for f in as_completed([pool.submit(discover,s,k) for s in syms if mapping[s] for k in ('klines','markPriceKlines','fundingRate')]):
            s,k,allkeys,keys=f.result();availability.setdefault(s,{})[k]=sorted(x[-11:-4] for x in allkeys);jobs.extend((x,False) for x in keys)
    for s,m in plans:
        if s in ('BTCUSDT','ETHUSDT'):continue
        for tf in ('1h','5m'):jobs.append((f'data/spot/monthly/klines/{s}/{tf}/{s}-{tf}-{m}.zip',True))
    dump(ROOT/'archive-plan.json',jobs);records=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        for i,f in enumerate(as_completed([pool.submit(archive,*j) for j in jobs]),1):
            records.append(f.result())
            if i%100==0:print('Verified archives',i,'/',len(jobs),flush=True)
    parts={}
    for r in records:
        key=r['key'];spot=key.startswith('data/spot');bits=key.split('/');s=bits[4] if spot else bits[5];kind=bits[5] if spot else bits[4]
        with zipfile.ZipFile(RESEARCH/r['file']) as z:d=pd.read_csv(z.open(z.namelist()[0]),header=None if spot else 0)
        if spot:
            d=d.iloc[:,[0,1,2,3,4,5,7,8,10]];d.columns=['date','open','high','low','close','volume','quote_volume','trades','buy_quote']
            d.date=pd.to_datetime(d.date.where(d.date<10**14,d.date//1000),unit='ms',utc=True)
        elif kind=='fundingRate':
            exact=pd.to_datetime(d.calc_time,unit='ms',utc=True);d['date']=exact.dt.round('h')
            assert (exact-d.date).dt.total_seconds().abs().max()<60
        else:d['date']=pd.to_datetime(d.open_time,unit='ms',utc=True)
        parts.setdefault(('spot' if spot else 'perp',s,kind),[]).append(d)
    manifest={'archives':records,'mapping':mapping,'availability':availability,'processed':{},'gaps':{},'old_hashes':{}}
    for (venue,s,kind),chunks in parts.items():
        d=pd.concat(chunks).drop_duplicates().sort_values('date').set_index('date');assert not d.index.duplicated().any(),(venue,s,kind)
        if kind!='fundingRate':
            # Repair isolated missing monthly bars from same-provider daily archives; never fill prices.
            step=3600 if kind=='1h' else 300
            gaps=[]
            for month,g in d.groupby(d.index.strftime('%Y-%m')):
                gaps.extend(pd.date_range(g.index.min(),g.index.max(),freq=f'{step}s').difference(g.index))
            for day in sorted({x.strftime('%Y-%m-%d') for x in gaps}):
                if venue=='spot':key=f'data/spot/daily/klines/{s}/{kind}/{s}-{kind}-{day}.zip'
                else:key=f'data/futures/um/daily/{kind}/{s}/5m/{s}-5m-{day}.zip'
                rec=archive(key,venue=='spot');manifest['archives'].append(rec)
                with zipfile.ZipFile(RESEARCH/rec['file']) as z:extra=pd.read_csv(z.open(z.namelist()[0]),header=None if venue=='spot' else 0)
                if venue=='spot':
                    extra=extra.iloc[:,[0,1,2,3,4,5,7,8,10]];extra.columns=['date','open','high','low','close','volume','quote_volume','trades','buy_quote']
                    extra.date=pd.to_datetime(extra.date.where(extra.date<10**14,extra.date//1000),unit='ms',utc=True)
                else:extra['date']=pd.to_datetime(extra.open_time,unit='ms',utc=True)
                extra=extra.set_index('date');d=pd.concat([d,extra.loc[~extra.index.isin(d.index)]]).sort_index()
            assert (d[['open','high','low','close']]>0).all().all()
        else:
            delta=d.index.to_series().diff().dt.total_seconds()/3600
            mismatch=delta.notna()&(delta-d.funding_interval_hours).abs().gt(.001)
            manifest['gaps'][s]=[{'from':d.index[i-1].isoformat(),'to':d.index[i].isoformat()} for i in np.flatnonzero(mismatch.to_numpy())]
        folder=ROOT/'data'/venue;folder.mkdir(parents=True,exist_ok=True);path=folder/f'{s}-{kind}.parquet';d.to_parquet(path)
        manifest['processed'][str(path.relative_to(ROOT))]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rows':len(d),'first':d.index[0].isoformat(),'last':d.index[-1].isoformat()}
    for parent,names in [(p.ROOT,['frozen.json','pool_engine.py','execution.py','execution-data-manifest.json']),(p.OLD,['pool-daily.parquet','automatic_engine.py','automatic-protocol-v2.json','sizing-metrics.json'])]:
        for n in names:manifest['old_hashes'][str((parent/n).relative_to(RESEARCH))]=hashlib.sha256((parent/n).read_bytes()).hexdigest()
    dump(ROOT/'data-manifest.json',manifest);print('Ready',len(manifest['processed']),'processed files; old studies unchanged',flush=True)

if __name__=='__main__':main()
