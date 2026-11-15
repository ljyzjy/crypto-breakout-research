"""Extract signed 5-second taker notional before the simulated entry reference."""
import concurrent.futures,hashlib,io,json,threading,time
from pathlib import Path
import numpy as np
import pandas as pd
import requests
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(spec):
    contract,day,events=spec;name=f'{contract}-aggTrades-{day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    error='unknown'
    for attempt in range(3):
      try:
        h=session().get(url+'.CHECKSUM',timeout=(12,45));h.raise_for_status();sha=h.text.strip().split()[0].lower()
        response=session().get(url,timeout=(12,120));response.raise_for_status();body=response.content
        if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('checksum_mismatch')
        for e in events:
            if sha!=e['archive_sha256']:raise ValueError('archive_changed_since_first_touch')
        collected={e['observation_id']:[] for e in events}
        cols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
        for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=cols,
                                 dtype={'is_buyer_maker':str},chunksize=150_000):
            times=chunk.transact_time.to_numpy(np.int64)
            for e in events:
                t=int(e['decision_ts']);part=chunk.loc[(times>t)&(times<t+5000)]
                if len(part):collected[e['observation_id']].append(part)
        rows=[]
        for e in events:
            parts=collected[e['observation_id']]
            if not parts:
                rows.append({'observation_id':e['observation_id'],'status':'empty_window','count':0,'archive_sha256':sha});continue
            ticks=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            maker=ticks.is_buyer_maker.str.lower()
            if not maker.isin(['true','false']).all():raise ValueError('unexpected_maker_flag')
            values=ticks.price.to_numpy(float)*ticks.quantity.to_numpy(float)
            if not np.isfinite(values).all() or (values<=0).any():raise ValueError('invalid_trade_notional')
            buy=float(values[maker.eq('false').to_numpy()].sum());sell=float(values[maker.eq('true').to_numpy()].sum())
            total=buy+sell
            rows.append({'observation_id':e['observation_id'],'status':'verified','archive_sha256':sha,
              'count':len(ticks),'buy_notional':buy,'sell_notional':sell,'total_notional':total,
              'directional_imbalance':int(e['side'])*(buy-sell)/total,'first_ts':int(ticks.transact_time.iloc[0]),
              'last_ts':int(ticks.transact_time.iloc[-1]),'window_end':int(e['decision_ts'])+5000})
        return {'contract':contract,'day':day,'status':'verified','sha256':sha,'bytes':len(body),'rows':rows}
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:120]
        if attempt<2:time.sleep(1+attempt)
    return {'contract':contract,'day':day,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error','count':0} for e in events]}
def main():
    src=PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet'
    d=pd.read_parquet(src);d=d[d.status.eq('verified')&d.source_year.eq('2026')].copy()
    tasks=[(c,day,g.to_dict('records')) for (c,day),g in d.groupby(['contract','day'])];results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(task,x) for x in tasks]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            if len(results)%10==0:print('FIVE_SECOND_FLOW_ARCHIVES',len(results),'/',len(tasks),flush=True)
    rows=[x for r in results for x in r.pop('rows')];out=pd.DataFrame(rows)
    assert len(out)==len(d) and out.observation_id.is_unique
    out.to_parquet(HERE/'五秒主动成交特征_2026.parquet',index=False)
    meta={'events':len(d),'archives':len(tasks),'verified_archives':sum(r['status']=='verified' for r in results),
          'statuses':out.status.value_counts().to_dict(),'at_least_three':int(out['count'].ge(3).sum()),
          'archive_errors':[r for r in results if r['status']!='verified'],'bytes_downloaded':sum(r.get('bytes',0) for r in results),
          'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'archives_detail':results}
    (HERE/'五秒主动成交档案校验.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIVE_SECOND_FLOW_EXTRACT_COMPLETE',json.dumps({k:meta[k] for k in ['events','archives','statuses','at_least_three','archive_errors','bytes_downloaded']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
