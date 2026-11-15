"""Bounded-memory public trade replay; original candidate and decision rules are reused."""
import hashlib,io,json,shutil,tempfile,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import extract_old11_tapes as original
H=Path(__file__).resolve().parent;ROOT=original.ROOT;ENGINE=original.engine;M=60_000
WORK=ROOT/'work'/'old11_2023_dual'/'stream_tape_tight';TEMP=ROOT/'work'/'old11_2023_dual'/'stream_temp_tight'
WORK.mkdir(parents=True,exist_ok=True);TEMP.mkdir(parents=True,exist_ok=True)
FP=hashlib.sha256(Path(__file__).read_bytes()+original.FP.encode()).hexdigest()
DISK_MIN=2_200_000_000;MEM_MIN=750*1024**2;MAX_ARCHIVE=200_000_000
def key_for(spec):
    contract,day,needs,events=spec
    return hashlib.sha256((FP+'|'+contract+'|'+day+'|'+str(needs)+'|'+'|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest()
def stream_archive(contract,day):
    name=f'{contract}-aggTrades-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    s=ENGINE.session();c=s.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();expected=c.text.strip().split()[0].lower()
    f=tempfile.NamedTemporaryFile(prefix='tape_',suffix='.zip',dir=TEMP,delete=False);path=Path(f.name)
    assert path.resolve().parent==TEMP.resolve() and not path.is_symlink()
    try:
        size=0;sha=hashlib.sha256()
        with f:
          with s.get(url,headers={'Accept-Encoding':'identity'},stream=True,timeout=(15,120)) as response:
            response.raise_for_status();length=response.headers.get('Content-Length')
            if length is not None and int(length)>MAX_ARCHIVE:raise RuntimeError('archive_exceeds_stream_cap')
            for chunk in response.iter_content(chunk_size=1024*1024):
                if not chunk:continue
                if shutil.disk_usage(ROOT).free-len(chunk)<DISK_MIN:raise RuntimeError('disk_headroom')
                size+=len(chunk)
                if size>MAX_ARCHIVE:raise RuntimeError('archive_exceeds_stream_cap')
                f.write(chunk);sha.update(chunk)
        if length is not None and size!=int(length):raise ValueError('archive_size_mismatch')
        if sha.hexdigest()!=expected:raise ValueError('checksum_mismatch')
        return path,{'kind':'aggTrades','day':day,'sha256':expected,'bytes':size}
    except BaseException:
        if path.exists():path.unlink()
        raise
def task(spec,work=WORK):
    contract,day,needs,events=spec;path=work/(key_for(spec)+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<MEM_MIN:
            time.sleep(3)
            if shutil.disk_usage(ROOT).free<DISK_MIN:raise RuntimeError('disk_headroom')
        if shutil.disk_usage(ROOT).free<DISK_MIN:raise RuntimeError('disk_headroom')
        body,bar_meta=ENGINE.archive('klines',contract,day);bars=ENGINE.minute_bars(body,day);del body
        loc=pd.read_parquet(original.NORM/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        bad=set()
        for e in events:
            ts=np.arange(int(e['quarter_start']),int(e['trigger_minute'])+M,M,dtype=np.int64)
            x=loc.reindex(ts);y=bars.reindex(ts);cols=['open','high','low','close']
            if not np.isfinite(x[cols].to_numpy(float)).all() or not np.isfinite(y[cols].to_numpy(float)).all() or not np.allclose(x[cols],y[cols],rtol=1e-9,atol=1e-12):bad.add(e['observation_id'])
        archives=[bar_meta];dates=[day]
        if needs:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        blocks={e['observation_id']:[] for e in events}
        for date in dates:
            temp,meta=stream_archive(contract,date);archives.append(meta)
            try:
                cols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
                for chunk in pd.read_csv(temp,compression='zip',usecols=cols,dtype={'is_buyer_maker':str},chunksize=10_000):
                    t=chunk.transact_time.to_numpy(np.int64)
                    for e in events:
                        z=chunk.loc[(t>=int(e['trigger_minute']))&(t<int(e['quarter_end'])+60_000)]
                        if len(z):blocks[e['observation_id']].append(z)
            finally:
                assert temp.resolve().parent==TEMP.resolve() and not temp.is_symlink()
                if temp.exists():temp.unlink()
        rows=[]
        for e in events:
            obs=e['observation_id']
            if e['market_prior_status']!='allowed':rows.append({'observation_id':obs,'status':'market_data_unknown'});continue
            if obs in bad:rows.append({'observation_id':obs,'status':'daily_monthly_ohlc_mismatch'});continue
            if not blocks[obs]:rows.append({'observation_id':obs,'status':'missing_event_tape'});continue
            tape=pd.concat(blocks[obs],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            rows.append({'observation_id':obs,**ENGINE.decide(e,tape,bars)})
        out={'contract':contract,'day':day,'needs_next':needs,'status':'verified','archives':archives,'rows':rows}
        if shutil.disk_usage(ROOT).free<DISK_MIN:raise RuntimeError('disk_headroom')
        work.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path);return out
      except Exception as e:
        error=type(e).__name__+':'+str(e)[:140]
        if 'headroom' in error or 'stream_cap' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error'} for e in events]}
