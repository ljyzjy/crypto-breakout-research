"""Causal daily pool and checksum-verified minute archives; never examines returns."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib, json, sys, zipfile, shutil, time
import numpy as np
import pandas as pd
import psutil

ROOT=Path(__file__).resolve().parent
RESEARCH=ROOT.parent
sys.path.insert(0,str(RESEARCH/'coin-lab-v1'))
from download_pool import fetch, listing

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(p)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def daily_pools(frame, start, end):
    spec=read(RESEARCH/'coin-lab-v1/automatic-protocol-v2.json')
    excluded={x+'USDT' for x in spec['exclusions']}
    assets=set(frame.symbol.str[:-4])
    for a in assets:
        for x,y in [('UP','DOWN'),('DOWN','UP'),('BULL','BEAR'),('BEAR','BULL')]:
            if a.endswith(x) and a[:-len(x)]+y in assets:excluded.add(a+'USDT')
    idx=pd.date_range('2024-09-01',pd.Timestamp(end)-pd.Timedelta(days=1),tz='UTC')
    byday={}
    for s,raw in frame.groupby('symbol'):
        if s in excluded:continue
        d=raw.set_index('date').reindex(idx)
        valid=d.close.gt(0)&d.volume.gt(0)&d.quote_volume.gt(0)
        liq=d.quote_volume.where(valid).rolling(30).median()
        good=valid.rolling(90).sum().eq(90)&liq.ge(10_000_000)
        for t,v in liq[good].items():
            day=(t+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            if start<=day<=end:byday.setdefault(day,[]).append({'symbol':s,'liquidity':float(v)})
    return [{'date':d.strftime('%Y-%m-%d'),'known_through':(d-pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
             'eligible_count':len(byday.get(d.strftime('%Y-%m-%d'),[])),
             'pool':sorted(byday.get(d.strftime('%Y-%m-%d'),[]),key=lambda x:(-x['liquidity'],x['symbol']))[:20]}
            for d in pd.date_range(start,end)], sorted(excluded)

def prepare():
    spec=read(ROOT/'protocol.json')
    original=RESEARCH/'coin-lab-v1/pool-daily.parquet'
    assert sha(original)==read(RESEARCH/'coin-lab-v1/pool-data-manifest.json')['pool_sha256']
    pools,excluded=daily_pools(pd.read_parquet(original),spec['start'],spec['end'])
    dump(ROOT/'daily-pools.json',pools)
    known=read(RESEARCH/'selection-event-v4/data-manifest.json')['mapping']
    union=sorted({p['symbol'] for row in pools for p in row['pool']})
    unknown=[s for s in union if s not in known]
    if unknown:
        contracts={k.split('/')[-2] for k in listing('data/futures/um/monthly/klines/','/')}
        for s in unknown:known[s]=s if s in contracts else ('1000'+s if '1000'+s in contracts else None)
    days={s:set() for s in union}
    for row in pools:
        for p in row['pool']:
            # Warmup and next day provide all past factors and exits after pool departure.
            for offset in range(-3,2):
                days[p['symbol']].add((pd.Timestamp(row['date'])+pd.Timedelta(days=offset)).strftime('%Y-%m-%d'))
    months=sorted({(known[s],d[:7]) for s,ds in days.items() if known.get(s) for d in ds})
    plan={'mapping':{s:known.get(s) for s in union},'days':{s:sorted(ds) for s,ds in days.items()},
          'months':months,'daily_sha256':sha(original),'exclusions':excluded,'protocol_sha256':sha(ROOT/'protocol.json')}
    dump(ROOT/'data-plan.json',plan)
    kit=RESEARCH.parent;saved=read(kit/'user_data/dashboard-processes.local.json')
    engine=psutil.Process(saved['engine']['pid'])
    assert abs(engine.create_time()-saved['engine']['created'])<.01
    assert 'DailyMomentum' in engine.cmdline()
    protected=read(RESEARCH/'selection-data-gate-v2/paper-before.json')['hashes']
    assert all(sha(kit/p)==h for p,h in protected.items())
    dump(ROOT/'paper-before.json',{'processes':saved,'hashes':protected})
    dump(ROOT/'registration.json',{'registered_utc':pd.Timestamp.now(tz='UTC').isoformat(),
        'protocol_sha256':sha(ROOT/'protocol.json'),'daily_pools_sha256':sha(ROOT/'daily-pools.json'),
        'data_plan_sha256':sha(ROOT/'data-plan.json'),'candidate_results_seen':False})
    print('PLAN',len(union),'spot candidates',len(months),'contract-months', 'freeGB',round(shutil.disk_usage(ROOT).free/1e9,1),flush=True)
    return plan

def get_listing(contract,kind):
    prefix=f'data/futures/um/monthly/{kind}/{contract}/'+('1m/' if kind!='fundingRate' else '')
    p=ROOT/'listings'/f'{contract}-{kind}.json'
    if not p.exists():dump(p,[k for k in listing(prefix) if k.endswith('.zip')])
    return set(read(p))

def archive(job):
    contract,month,kind,key=job
    dest=ROOT/'data'/kind/contract/(month+'.parquet')
    record=dest.with_suffix('.json')
    if record.exists() and dest.exists():
        r=read(record)
        assert sha(dest)==r['parquet_sha256']
        return r
    if shutil.disk_usage(ROOT).free<2_000_000_000:raise RuntimeError('Less than2GB free; acquisition safely stopped')
    zpath=ROOT/'archives'/kind/key.split('/')[-1];zpath.parent.mkdir(parents=True,exist_ok=True)
    checksum=zpath.with_suffix('.sha256')
    expected=checksum.read_text().strip() if checksum.exists() else fetch('https://data.binance.vision/'+key+'.CHECKSUM').decode().split()[0]
    blob=zpath.read_bytes() if zpath.exists() else fetch('https://data.binance.vision/'+key)
    got=hashlib.sha256(blob).hexdigest();assert got==expected,key
    if not zpath.exists():zpath.write_bytes(blob);checksum.write_text(got)
    with zipfile.ZipFile(zpath) as z:d=pd.read_csv(z.open(z.namelist()[0]))
    if kind=='fundingRate':
        d['ts']=pd.to_numeric(d.calc_time).astype('int64')
        d=d[['ts','funding_interval_hours','last_funding_rate']]
    else:
        d['ts']=pd.to_numeric(d.open_time).astype('int64')
        cols=['ts','open','high','low','close']+(['volume','quote_volume'] if kind=='klines' else [])
        d=d[cols]
        for col in cols[1:]:d[col]=pd.to_numeric(d[col],errors='raise')
        assert (d[['open','high','low','close']]>0).all().all(),key
        assert d.high.ge(d[['open','close','low']].max(axis=1)).all(),key
        assert d.low.le(d[['open','close','high']].min(axis=1)).all(),key
    assert not d.ts.duplicated().any(),key
    assert pd.to_datetime(d.ts,unit='ms',utc=True).dt.strftime('%Y-%m').eq(month).all(),key
    d=d.sort_values('ts');dest.parent.mkdir(parents=True,exist_ok=True);d.to_parquet(dest,index=False)
    r={'contract':contract,'month':month,'kind':kind,'key':key,'archive_sha256':got,
       'path':str(dest.relative_to(ROOT)),'parquet_sha256':sha(dest),'rows':len(d),
       'first_ts':int(d.ts.min()),'last_ts':int(d.ts.max())}
    dump(record,r);return r

def acquire(plan):
    combos=sorted({(c,k) for c,m in plan['months'] for k in ('klines','markPriceKlines','fundingRate')})
    available={}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for pair,keys in zip(combos,pool.map(lambda x:get_listing(*x),combos)):available[pair]=keys
    jobs=[];missing=[]
    for c,m in plan['months']:
        for k in ('klines','markPriceKlines','fundingRate'):
            key=f'data/futures/um/monthly/{k}/{c}/'+(f'1m/{c}-1m-{m}.zip' if k!='fundingRate' else f'{c}-fundingRate-{m}.zip')
            if key in available[c,k]:jobs.append((c,m,k,key))
            else:missing.append({'contract':c,'month':m,'kind':k})
    dump(ROOT/'archive-plan.json',{'jobs':jobs,'missing':missing})
    print('DOWNLOAD',len(jobs),'archives',len(missing),'absent historical months',flush=True)
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(archive,j) for j in jobs]
        for i,f in enumerate(as_completed(futures),1):
            records.append(f.result())
            if i%50==0 or i==len(jobs):
                dump(ROOT/'progress.json',{'stage':'data','completed':i,'total':len(jobs),'utc':pd.Timestamp.now(tz='UTC').isoformat()})
                print('VERIFIED',i,'/',len(jobs),flush=True)
    dump(ROOT/'data-manifest.json',{'records':sorted(records,key=lambda r:r['key']),'missing':missing,
        'mapping':plan['mapping'],'protocol_sha256':sha(ROOT/'protocol.json'),'retrieved_utc':pd.Timestamp.now(tz='UTC').isoformat()})
    print('MINUTE DATA READY',len(records),flush=True)

if __name__=='__main__':
    p=read(ROOT/'data-plan.json') if (ROOT/'data-plan.json').exists() else prepare()
    acquire(p)
