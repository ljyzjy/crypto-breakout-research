"""Bounded-memory official tape replay for new fixed-11 candidate groups."""
import hashlib,json,shutil,sys,tempfile,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;I=H/'逐笔冻结输入';M=60_000
ORIG=P/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(ORIG));import extract_dynamic_tapes as engine
WORK=ROOT/'work'/'fixed11_cross46'/'tape';TEMP=ROOT/'work'/'fixed11_cross46'/'temp';WORK.mkdir(parents=True,exist_ok=True);TEMP.mkdir(parents=True,exist_ok=True)
FP=hashlib.sha256(Path(__file__).read_bytes()+(H/'逐笔输入冻结哈希.json').read_bytes()+(H/'逐笔复用计划.parquet').read_bytes()+
                  (ORIG/'tape_decision.py').read_bytes()+(ORIG/'leveraged_paths.py').read_bytes()).hexdigest()
DISK_MIN=2_200_000_000;MEM_MIN=500*1024**2;MAX_ARCHIVE=200_000_000
def key_for(spec):
    contract,day,needs,events=spec
    return hashlib.sha256((FP+'|'+contract+'|'+day+'|'+str(needs)+'|'+'|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest()
def stream_archive(contract,day):
    name=f'{contract}-aggTrades-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    s=engine.session();c=s.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();expected=c.text.strip().split()[0].lower()
    f=tempfile.NamedTemporaryFile(prefix='fixed11_',suffix='.zip',dir=TEMP,delete=False);path=Path(f.name)
    assert path.resolve().parent==TEMP.resolve() and not path.is_symlink()
    try:
        size=0;digest=hashlib.sha256()
        with f:
            with s.get(url,headers={'Accept-Encoding':'identity'},stream=True,timeout=(15,120)) as r:
                r.raise_for_status();length=r.headers.get('Content-Length')
                if length is not None and int(length)>MAX_ARCHIVE:raise RuntimeError('archive_exceeds_stream_cap')
                for b in r.iter_content(chunk_size=1024*1024):
                    if not b:continue
                    if shutil.disk_usage(ROOT).free-len(b)<DISK_MIN:raise RuntimeError('disk_headroom')
                    size+=len(b)
                    if size>MAX_ARCHIVE:raise RuntimeError('archive_exceeds_stream_cap')
                    f.write(b);digest.update(b)
        if length is not None and size!=int(length):raise ValueError('archive_size_mismatch')
        if digest.hexdigest()!=expected:raise ValueError('checksum_mismatch')
        return path,{'kind':'aggTrades','day':day,'sha256':expected,'bytes':size}
    except BaseException:
        if path.exists():path.unlink()
        raise
def task(spec):
    contract,day,needs,events=spec;file=WORK/(key_for(spec)+'.json')
    if file.exists():return json.loads(file.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<MEM_MIN:
            if shutil.disk_usage(ROOT).free<DISK_MIN:raise RuntimeError('disk_headroom')
            time.sleep(3)
        if shutil.disk_usage(ROOT).free<DISK_MIN:raise RuntimeError('disk_headroom')
        body,bar_meta=engine.archive('klines',contract,day);bars=engine.minute_bars(body,day);del body
        folder='breakout_2024_11' if day[:4]=='2024' else 'breakout_forward_2026'
        loc=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        bad=set()
        for e in events:
            ts=np.arange(int(e['quarter_start']),int(e['trigger_minute'])+M,M,dtype=np.int64)
            x=loc.reindex(ts);y=bars.reindex(ts);cols=['open','high','low','close']
            if not np.isfinite(x[cols].to_numpy(float)).all() or not np.isfinite(y[cols].to_numpy(float)).all() or not np.allclose(x[cols],y[cols],rtol=1e-9,atol=1e-12):bad.add(e['observation_id'])
        usable=[e for e in events if e['observation_id'] not in bad and e['market_prior_status']=='allowed']
        archives=[bar_meta];dates=[day]
        if needs:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        blocks={e['observation_id']:[] for e in usable}
        if usable:
          for date in dates:
            temp,meta=stream_archive(contract,date);archives.append(meta)
            try:
                cols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
                for chunk in pd.read_csv(temp,compression='zip',usecols=cols,dtype={'is_buyer_maker':str},chunksize=30_000):
                    t=chunk.transact_time.to_numpy(np.int64)
                    for e in usable:
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
            rows.append({'observation_id':obs,**engine.decide(e,tape,bars)})
        out={'contract':contract,'day':day,'needs_next':needs,'status':'verified','archives':archives,'rows':rows}
        if shutil.disk_usage(ROOT).free<DISK_MIN:raise RuntimeError('disk_headroom')
        temp=file.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(file);return out
      except Exception as e:
        error=type(e).__name__+':'+str(e)[:140]
        if 'headroom' in error or 'stream_cap' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error'} for e in events]}
def main():
    audit=json.loads((H/'新逐笔读取一致性核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['stream_fingerprint']==FP
    info=json.loads((H/'逐笔复用计划质量.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'逐笔复用计划.parquet').read_bytes()).hexdigest()==info['plan_sha256']
    plan=pd.read_parquet(H/'逐笔复用计划.parquet');need=set(plan.loc[plan.reuse_status.eq('need_new_tape'),'observation_id'])
    d=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True);d=d[d.observation_id.isin(need)]
    assert len(d)==len(need)
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]));done=0;errors=[]
    print('FIXED11_46_NEW_TAPE_TASKS',len(tasks),'events',len(d),flush=True)
    for spec in tasks:
        if shutil.disk_usage(ROOT).free<DISK_MIN:break
        r=task(spec)
        if r['status']!='verified':
            errors.append({'contract':r['contract'],'day':r['day'],'error':r.get('error')})
            if 'headroom' in r.get('error',''):break
        done+=1
        if done%5==0:print('FIXED11_46_NEW_TAPES',done,'/',len(tasks),'errors',len(errors),flush=True)
    out={'processed_tasks':done,'total_tasks':len(tasks),'errors':errors,'fingerprint':FP,
         'free_bytes':shutil.disk_usage(ROOT).free,'note':'Failed or unprocessed tasks remain unknown, not zero trades.'}
    (H/'新增逐笔重放进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_NEW_TAPES_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
