"""Reuse verified existing tapes and extract new 18-pool first-touch/5s flow."""
import concurrent.futures,hashlib,io,json,shutil,threading,time,sys
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent;M=60_000
sys.path.insert(0,str(PARENT));import flow_research as flow
local=threading.local();MIN_FREE=1_900_000_000
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def verified_row(e,ticks,sha):
    t=int(e['trigger_minute']);first=ticks[ticks.transact_time.lt(t+M)]
    crosses=first[(first.price>e['upper'])|(first.price<e['lower'])]
    if crosses.empty:return {**e,'status':'ohlc_trade_mismatch','archive_sha256':sha}
    cross=crosses.iloc[0];decision=int(cross.transact_time);side=1 if float(cross.price)>e['upper'] else -1
    if not e['long_known_eligible' if side==1 else 'short_known_eligible']:
        return {**e,'status':'first_direction_ineligible','archive_sha256':sha}
    if decision+5000>=int(e['quarter_end']):return {**e,'status':'expired_before_arrival','archive_sha256':sha}
    after=ticks[ticks.transact_time.ge(decision+5000)]
    if after.empty:return {**e,'status':'no_price_reference','archive_sha256':sha}
    entry=after.iloc[0];execution=int(entry.transact_time);entry_bar=execution//M*M
    if execution>=int(e['quarter_end']):return {**e,'status':'no_price_before_candle_end','archive_sha256':sha}
    suffix=ticks[ticks.transact_time.ge(execution)&ticks.transact_time.lt(entry_bar+M)]
    if suffix.empty:raise ValueError('missing_entry_suffix')
    window=ticks[ticks.transact_time.gt(decision)&ticks.transact_time.lt(decision+5000)]
    if len(window):
        maker=window.is_buyer_maker.str.lower();values=window.price.to_numpy(float)*window.quantity.to_numpy(float)
        if not maker.isin(['true','false']).all() or not np.isfinite(values).all() or (values<=0).any():raise ValueError('invalid_window')
        buy=float(values[maker.eq('false').to_numpy()].sum());sell=float(values[maker.eq('true').to_numpy()].sum());total=buy+sell
        extra={'five_status':'verified','five_count':len(window),'buy_notional':buy,'sell_notional':sell,'total_notional':total,
               'five_imbalance':side*(buy-sell)/total,'first_ts':int(window.transact_time.iloc[0]),
               'last_ts':int(window.transact_time.iloc[-1]),'window_end':decision+5000,'flow_archive_sha':sha}
    else:extra={'five_status':'empty_window','five_count':0,'buy_notional':0.,'sell_notional':0.,'total_notional':0.,
                'five_imbalance':None,'first_ts':None,'last_ts':None,'window_end':decision+5000,'flow_archive_sha':sha}
    spec=json.loads(e['long_spec'] if side==1 else e['short_spec'])
    return {**e,**spec,**extra,'observation_id':e['observation_id']+'|'+str(side),'status':'verified','archive_sha256':sha,
       'side':side,'ts':entry_bar,'decision_ts':decision,'feature_known_ts':t,'signal_close':float(cross.price),
       'break_ts':t,'touch_ts':decision,'entry_exec_ts':execution,'raw_entry_5s':float(entry.price),
       'suffix_high':float(suffix.price.max()),'suffix_low':float(suffix.price.min()),'suffix_close':float(suffix.price.iloc[-1]),
       'suffix_trade_count':len(suffix),'risk_multiplier':1.,'tape_source':'downloaded'}
def task(spec):
    contract,day,events=spec;name=f'{contract}-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}';error='unknown'
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('insufficient_disk_reserve')
        check=session().get(url+'.CHECKSUM',timeout=(12,45));check.raise_for_status();sha=check.text.strip().split()[0].lower()
        response=session().get(url,timeout=(12,120));response.raise_for_status();body=response.content
        if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('checksum_mismatch')
        collected={e['observation_id']:[] for e in events}
        cols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
        for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=cols,dtype={'is_buyer_maker':str},chunksize=150_000):
            times=chunk.transact_time.to_numpy(np.int64)
            for e in events:
                t=int(e['trigger_minute']);end=min(t+2*M,int(e['quarter_end']))
                part=chunk.loc[(times>=t)&(times<end)]
                if len(part):collected[e['observation_id']].append(part)
        rows=[]
        for e in events:
            parts=collected[e['observation_id']]
            if not parts:rows.append({**e,'status':'no_trigger_data','archive_sha256':sha,'tape_source':'downloaded'});continue
            ticks=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            row=verified_row(e,ticks,sha);row.setdefault('tape_source','downloaded');rows.append(row)
        return {'contract':contract,'day':day,'status':'verified','sha256':sha,'bytes':len(body),'rows':rows}
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:100]
        if 'insufficient_disk_reserve' in error:break
        if attempt<2:time.sleep(1+attempt)
    return {'contract':contract,'day':day,'status':'error','error':error,
            'rows':[{**e,'status':'archive_error','tape_source':'downloaded'} for e in events]}
def main():
    cand=pd.read_parquet(HERE/'十八币潜在首次触价.parquet')
    old=pd.read_parquet(PARENT/'第二十六轮_全时段五秒主动成交'/'全时段五秒特征候选.parquet').copy()
    old['base_id']=old.observation_id.str.rsplit('|',n=1).str[0];assert old.base_id.is_unique
    lookup=old.set_index('base_id');reused=[];fresh=[]
    copycols=['decision_ts','ts','feature_known_ts','signal_close','break_ts','touch_ts','entry_exec_ts','raw_entry_5s',
              'suffix_high','suffix_low','suffix_close','suffix_trade_count','five_status','five_count','buy_notional',
              'sell_notional','total_notional','five_imbalance','first_ts','last_ts','window_end','flow_archive_sha','archive_sha256']
    for e in cand.to_dict('records'):
        if e['observation_id'] not in lookup.index:fresh.append(e);continue
        prev=lookup.loc[e['observation_id']];side=int(prev.side)
        for k in ('upper','lower','atr'):
            if not np.isclose(float(e[k]),float(prev[k]),rtol=1e-10,atol=1e-12):raise ValueError('reused_price_feature_mismatch')
        if not e['long_known_eligible' if side==1 else 'short_known_eligible']:
            reused.append({**e,'status':'first_direction_ineligible','archive_sha256':prev.archive_sha256,'tape_source':'reused'});continue
        if prev.archive_sha256!=prev.flow_archive_sha:raise ValueError('reused_archive_mismatch')
        rule=json.loads(e['long_spec'] if side==1 else e['short_spec'])
        copied={k:prev[k] for k in copycols}
        reused.append({**e,**rule,**copied,'observation_id':e['observation_id']+'|'+str(side),'status':'verified',
                       'side':side,'risk_multiplier':1.,'tape_source':'reused'})
    pending=pd.DataFrame(fresh);tasks=[]
    if len(pending):
        tasks=[(c,day,g.to_dict('records')) for (c,day),g in pending.groupby(['contract','day'])]
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(task,x) for x in tasks]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            if len(results)%20==0:print('EXPANDED18_TAPES',len(results),'/',len(tasks),flush=True)
    downloaded=[row for result in results for row in result.pop('rows')];d=pd.DataFrame(reused+downloaded)
    assert len(d)==len(cand)
    mismatches=[];missing_labels=[]
    for (year,contract),g in d[d.status.eq('verified')].groupby(['source_year','contract']):
        folder='breakout_november_2026' if year=='2026' else 'breakout_2024_expanded18'
        raw=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        for ix,r in g.iterrows():
            if int(r.ts) not in raw.index or int(r.quarter_start) not in raw.index or int(r.quarter_end)-M not in raw.index:
                missing_labels.append(r.observation_id);continue
            b=raw.loc[int(r.ts)];open0=float(raw.at[int(r.quarter_start),'open']);close=float(raw.at[int(r.quarter_end)-M,'close'])
            good=(np.isfinite([b.high,b.low,b.close,open0,close]).all() and r.suffix_high<=b.high*(1+1e-9) and
                  r.suffix_low>=b.low*(1-1e-9) and np.isclose(r.suffix_close,b.close,rtol=1e-9,atol=1e-12) and
                  r.entry_exec_ts>=r.decision_ts+5000 and r.entry_exec_ts<r.quarter_end)
            if not good:mismatches.append(r.observation_id)
            body=int(r.side)*(close-open0)/open0;beyond=int(r.side)*(close-float(r.level))>0
            d.loc[ix,'large_1pct_label']=bool(body>=.01 and beyond)
            d.loc[ix,'large_halfpct_label']=bool(body>=.005 and beyond)
            d.loc[ix,'completed_body_pct']=100*body
    d.loc[d.observation_id.isin(mismatches),'status']='minute_archive_mismatch'
    d.loc[d.observation_id.isin(missing_labels),'status']='missing_completed_candle'
    d.to_parquet(HERE/'十八币首次触价五秒成交.parquet',index=False)
    meta={'candidate_events':len(cand),'reuse_base_matches':len(reused),'new_events':len(fresh),'new_archives':len(tasks),
          'verified_new_archives':sum(x['status']=='verified' for x in results),'statuses':d.status.value_counts().to_dict(),
          'source_counts':d.tape_source.value_counts().to_dict(),'minute_mismatches':mismatches,'missing_completed_candles':missing_labels,
          'archive_errors':[x for x in results if x['status']!='verified'],'bytes_downloaded':sum(x.get('bytes',0) for x in results),
          'disk_free_bytes':shutil.disk_usage(ROOT).free,'archives':results}
    flow.dump(HERE/'十八币逐笔核验清单.json',meta)
    print('EXPANDED18_TAPES_COMPLETE',json.dumps({k:meta[k] for k in ['candidate_events','reuse_base_matches','new_events','new_archives','statuses','minute_mismatches','missing_completed_candles','archive_errors','bytes_downloaded','disk_free_bytes']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
