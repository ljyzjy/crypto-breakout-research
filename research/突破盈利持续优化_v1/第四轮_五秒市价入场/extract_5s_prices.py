"""Checksum public aggTrades, retain only post-arrival prices for candidate minutes."""
import concurrent.futures
import hashlib
import io
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROOT=HERE.parent.parent.parent
M=60_000
local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(spec):
    contract,day,events=spec
    name=f'{contract}-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    error='unknown'
    for attempt in range(3):
      try:
        chk=session().get(url+'.CHECKSUM',timeout=(12,45));chk.raise_for_status()
        expected=chk.text.strip().split()[0].lower()
        res=session().get(url,timeout=(12,120));res.raise_for_status();body=res.content
        if hashlib.sha256(body).hexdigest()!=expected:raise ValueError('checksum_mismatch')
        bins={int(x['decision_ts']):{'first_ts':None,'first_price':None,'last_ts':None,'last_price':None,
                                      'high':-np.inf,'low':np.inf,'count':0} for x in events}
        for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['price','transact_time'],chunksize=150_000):
            t=chunk.transact_time.to_numpy(np.int64);p=chunk.price.to_numpy(float)
            if not np.isfinite(p).all() or (p<=0).any():raise ValueError('invalid_trade_price')
            for start,acc in bins.items():
                ix=np.flatnonzero((t>=start+5_000)&(t<start+M))
                if not len(ix):continue
                tt=t[ix];pp=p[ix];a=int(np.argmin(tt));z=int(np.flatnonzero(tt==tt.max())[-1])
                if acc['first_ts'] is None or int(tt[a])<acc['first_ts']:
                    acc['first_ts']=int(tt[a]);acc['first_price']=float(pp[a])
                if acc['last_ts'] is None or int(tt[z])>=acc['last_ts']:
                    acc['last_ts']=int(tt[z]);acc['last_price']=float(pp[z])
                acc['high']=max(acc['high'],float(pp.max()));acc['low']=min(acc['low'],float(pp.min()));acc['count']+=len(ix)
        rows=[]
        for e in events:
            start=int(e['decision_ts']);x=bins[start]
            if x['first_ts'] is None:
                rows.append({**e,'status':'no_trade_after_5s','archive_sha256':expected})
            else:
                rows.append({**e,'status':'verified','entry_exec_ts':x['first_ts'],'raw_entry_5s':x['first_price'],
                             'suffix_high':x['high'],'suffix_low':x['low'],'suffix_close':x['last_price'],
                             'suffix_last_ts':x['last_ts'],'suffix_trade_count':x['count'],'archive_sha256':expected})
        return {'contract':contract,'day':day,'status':'verified','sha256':expected,'bytes':len(body),'rows':rows}
      except Exception as exc:
        error=type(exc).__name__
        if attempt<2:time.sleep(1+attempt)
    return {'contract':contract,'day':day,'status':'error','error':error,
            'rows':[{**e,'status':'archive_error'} for e in events]}
def main():
    phase=sys.argv[1] if len(sys.argv)>1 else 'train'
    if phase=='train':
        specs=[('2024',PARENT/'2024反向跨期验证'/'2024因果候选与事后标签.parquet','2024-01-01','2024-07-01'),
               ('2026',PARENT/'2026因果候选与事后标签.parquet','2026-05-01','2026-08-01')]
    elif phase=='later':
        specs=[('2024',PARENT/'2024反向跨期验证'/'2024因果候选与事后标签.parquet','2024-07-01','2025-01-01'),
               ('2026',PARENT/'2026因果候选与事后标签.parquet','2026-08-01','2026-11-13')]
    elif phase=='2023':
        specs=[('2023',HERE/'2023因果候选与事后标签.parquet','2023-01-01','2024-01-01')]
    else:raise ValueError(phase)
    all_frames=[]
    for year,path,start,end in specs:
        d=pd.read_parquet(path);lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000);hi=int(pd.Timestamp(end,tz='UTC').timestamp()*1000)
        d=d[d.decision_ts.ge(lo)&d.decision_ts.lt(hi)].copy()
        # Preserve original late-day rejection; these candidates cannot enter.
        d=d[((d.decision_ts//M+480)%1440)<1320]
        d['day']=pd.to_datetime(d.decision_ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
        d['source_year']=year;all_frames.append(d)
    events=pd.concat(all_frames,ignore_index=True)
    assert events.observation_id.is_unique
    tasks=[]
    for (contract,day),g in events.groupby(['contract','day']):
        rows=g[['observation_id','contract','day','decision_ts','source_year']].to_dict('records')
        assert len({r['decision_ts'] for r in rows})==len(rows)
        tasks.append((contract,day,rows))
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(task,x) for x in tasks]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if len(results)%25==0:print('FIVE_SECOND_ARCHIVES',phase,len(results),'/',len(tasks),flush=True)
    rows=[r for x in results for r in x.pop('rows')]
    ticks=pd.DataFrame(rows)
    assert len(ticks)==len(events) and ticks.observation_id.is_unique
    bysymbol=events[['observation_id','contract','source_year']].set_index('observation_id')
    invalid=[]
    for (year,contract),g in ticks[ticks.status.eq('verified')].groupby(['source_year','contract']):
        norm=(ROOT/'work'/('breakout_november_2026' if year=='2026' else f'breakout_{year}_11')/'normalized')
        d=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','high','low','close']).set_index('ts')
        b=d.reindex(g.decision_ts.to_numpy(np.int64))
        for row,bar in zip(g.itertuples(index=False),b.itertuples(index=False)):
            ok=(np.isfinite([bar.high,bar.low,bar.close]).all() and
                row.suffix_high<=bar.high*(1+1e-9) and row.suffix_low>=bar.low*(1-1e-9) and
                np.isclose(row.suffix_close,bar.close,rtol=1e-9,atol=1e-12) and
                row.decision_ts+5000<=row.entry_exec_ts<row.decision_ts+M)
            if not ok:invalid.append(row.observation_id)
    ticks.loc[ticks.observation_id.isin(invalid),'status']='minute_archive_mismatch'
    ticks.sort_values(['decision_ts','contract']).to_parquet(HERE/f'五秒价格摘要_{phase}.parquet',index=False)
    meta={'phase':phase,'candidate_events':len(events),'daily_archives_requested':len(tasks),
          'archives_verified':sum(x['status']=='verified' for x in results),
          'archive_errors':[x for x in results if x['status']!='verified'],
          'entry_status_counts':ticks.status.value_counts().to_dict(),
          'minute_archive_mismatches':invalid,'bytes_downloaded':sum(x.get('bytes',0) for x in results),
          'data_note':'Public executed trade is a reference price, not a bid/ask quote or a guaranteed fill; 5s latency and adverse slippage are assumptions.',
          'archives':results}
    (HERE/f'五秒档案校验_{phase}.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIVE_SECOND_EXTRACTION_COMPLETE',phase,'events',len(events),'archives',len(tasks),
          'status',meta['entry_status_counts'],'bytes',meta['bytes_downloaded'],flush=True)
if __name__=='__main__':main()
