"""Resolve first intraminute cross and next 5s public trade without order books."""
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
ROOT=HERE.parent.parent.parent
M=60_000
local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(spec):
    contract,day,events=spec;name=f'{contract}-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    error='unknown'
    for attempt in range(3):
      try:
        checksum=session().get(url+'.CHECKSUM',timeout=(12,45));checksum.raise_for_status()
        expected=checksum.text.strip().split()[0].lower()
        response=session().get(url,timeout=(12,120));response.raise_for_status();body=response.content
        if hashlib.sha256(body).hexdigest()!=expected:raise ValueError('checksum_mismatch')
        collected={e['observation_id']:[] for e in events}
        for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=150_000):
            times=chunk.transact_time.to_numpy(np.int64)
            for e in events:
                t=int(e['trigger_minute']);end=min(t+2*M,int(e['quarter_end']))
                part=chunk.loc[(times>=t)&(times<end)]
                if len(part):collected[e['observation_id']].append(part)
        out=[]
        for e in events:
            parts=collected[e['observation_id']]
            if not parts:
                out.append({**e,'status':'no_trigger_data','archive_sha256':expected});continue
            ticks=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            t=int(e['trigger_minute']);first_minute=ticks[ticks.transact_time.lt(t+M)]
            crossed=first_minute[(first_minute.price>e['upper'])|(first_minute.price<e['lower'])]
            if crossed.empty:
                out.append({**e,'status':'ohlc_trade_mismatch','archive_sha256':expected});continue
            trigger=crossed.iloc[0];decision=int(trigger.transact_time)
            side=1 if float(trigger.price)>e['upper'] else -1
            if not e['long_known_eligible' if side==1 else 'short_known_eligible']:
                out.append({**e,'status':'first_direction_ineligible','archive_sha256':expected});continue
            if decision+5000>=int(e['quarter_end']):
                out.append({**e,'status':'expired_before_arrival','archive_sha256':expected});continue
            after=ticks[ticks.transact_time.ge(decision+5000)]
            if after.empty:
                out.append({**e,'status':'no_price_reference','archive_sha256':expected});continue
            entry=after.iloc[0];execution=int(entry.transact_time);entry_bar=execution//M*M
            if execution>=int(e['quarter_end']):
                out.append({**e,'status':'no_price_before_candle_end','archive_sha256':expected});continue
            suffix=ticks[(ticks.transact_time.ge(execution))&(ticks.transact_time.lt(entry_bar+M))]
            assert len(suffix)>0
            spec_row=json.loads(e['long_spec'] if side==1 else e['short_spec'])
            out.append({**e,**spec_row,'observation_id':e['observation_id']+'|'+str(side),
                'status':'verified','archive_sha256':expected,'side':side,'ts':entry_bar,
                'decision_ts':decision,'feature_known_ts':t,'signal_close':float(trigger.price),
                'break_ts':t,'touch_ts':decision,'entry_exec_ts':execution,'raw_entry_5s':float(entry.price),
                'suffix_high':float(suffix.price.max()),'suffix_low':float(suffix.price.min()),
                'suffix_close':float(suffix.price.iloc[-1]),'suffix_trade_count':len(suffix),
                'risk_multiplier':1.})
        return {'contract':contract,'day':day,'status':'verified','sha256':expected,'bytes':len(body),'rows':out}
      except Exception as exc:
        error=type(exc).__name__
        if attempt<2:time.sleep(1+attempt)
    return {'contract':contract,'day':day,'status':'error','error':error,
            'rows':[{**e,'status':'archive_error'} for e in events]}
def main():
    frames=[]
    phase=sys.argv[1] if len(sys.argv)>1 else 'train'
    if phase=='train':sets=[('2024',2024),('2026',2026)];label='训练'
    elif phase=='later':sets=[('2024h2',2024),('2026later',2026)];label='后续'
    elif phase=='2023':sets=[('2023full',2023)];label='2023'
    else:raise ValueError(phase)
    for tag,year in sets:
        d=pd.read_parquet(HERE/f'潜在触价候选_{tag}.parquet');d['source_year']=str(year)
        d['day']=pd.to_datetime(d.trigger_minute,unit='ms',utc=True).dt.strftime('%Y-%m-%d');frames.append(d)
    candidates=pd.concat(frames,ignore_index=True);tasks=[]
    for (c,day),g in candidates.groupby(['contract','day']):tasks.append((c,day,g.to_dict('records')))
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(task,t) for t in tasks]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            if len(results)%20==0:print('TOUCH_ARCHIVES',phase,len(results),'/',len(tasks),flush=True)
    rows=[r for result in results for r in result.pop('rows')]
    d=pd.DataFrame(rows);assert len(d)==len(candidates)
    mismatches=[]
    for (year,contract),g in d[d.status.eq('verified')].groupby(['source_year','contract']):
        norm=ROOT/'work'/('breakout_november_2026' if year=='2026' else f'breakout_{year}_11')/'normalized'
        raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        bar=raw.reindex(g.ts.to_numpy(np.int64))
        for r,b in zip(g.itertuples(index=False),bar.itertuples(index=False)):
            ok=(np.isfinite([b.high,b.low,b.close]).all() and r.suffix_high<=b.high*(1+1e-9) and
                r.suffix_low>=b.low*(1-1e-9) and np.isclose(r.suffix_close,b.close,rtol=1e-9,atol=1e-12) and
                r.entry_exec_ts>=r.decision_ts+5000 and r.entry_exec_ts<r.quarter_end)
            if not ok:mismatches.append(r.observation_id)
        # These labels are written only after first-touch and are removed before account replay.
        for idx,row in g.iterrows():
            opening=float(raw.at[int(row.quarter_start),'open']);closing=float(raw.at[int(row.quarter_end)-M,'close'])
            body=int(row.side)*(closing-opening)/opening;beyond=int(row.side)*(closing-float(row.level))>0
            d.loc[idx,'large_1pct_label']=bool(body>=.01 and beyond)
            d.loc[idx,'large_halfpct_label']=bool(body>=.005 and beyond)
            d.loc[idx,'completed_body_pct']=100*body
    d.loc[d.observation_id.isin(mismatches),'status']='minute_archive_mismatch'
    d.to_parquet(HERE/f'逐笔首次触价与五秒入场_{label}.parquet',index=False)
    meta={'candidate_minutes':len(candidates),'daily_archives':len(tasks),'verified_archives':sum(x['status']=='verified' for x in results),
          'statuses':d.status.value_counts().to_dict(),'minute_archive_mismatches':mismatches,
          'archive_errors':[x for x in results if x['status']!='verified'],'bytes_downloaded':sum(x.get('bytes',0) for x in results),
          'note':'Price is an observed trade plus modeled adverse slippage, not a guaranteed market-order fill.',
          'archives':results}
    (HERE/f'逐笔触价档案校验_{label}.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TOUCH_EXTRACTION_COMPLETE',phase,len(candidates),'status',meta['statuses'],'bytes',meta['bytes_downloaded'],flush=True)
if __name__=='__main__':main()
