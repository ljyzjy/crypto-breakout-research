"""Resolve completed open-only tape mismatches from official raw trade archives."""
import concurrent.futures,hashlib,io,json,shutil,threading,time
from collections import Counter
from pathlib import Path
import pandas as pd,requests
from extract_dynamic_tapes import minute_bars
from raw_reconciliation import reconcile
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent;M=60_000
SOURCE=PARENT/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet'
PLAN=HERE/'原始成交差异复核规则.json';ORIGINAL=ROOT/'work'/'point_in_time_universe33'/'tape'
WORK=ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation';WORK.mkdir(parents=True,exist_ok=True)
BASE='https://data.binance.vision/data/futures/um/daily/';local=threading.local();MIN_FREE=1_900_000_000
FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+(HERE/'raw_reconciliation.py').read_bytes()+PLAN.read_bytes()+SOURCE.read_bytes()).hexdigest()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def fetch(kind,symbol,day):
    path=f'klines/{symbol}/1m/{symbol}-1m-{day}.zip' if kind=='klines' else f'{kind}/{symbol}/{symbol}-{kind}-{day}.zip'
    c=session().get(BASE+path+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
    r=session().get(BASE+path,timeout=(15,120));r.raise_for_status()
    if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('checksum_mismatch')
    return r.content,{'kind':kind,'day':day,'sha256':sha,'bytes':len(r.content)}
def task(spec):
    contract,day,needs_next,events,old_archives=spec
    key=hashlib.sha256((FINGERPRINT+'|'+contract+'|'+day+'|'+str(needs_next)+'|'+
                       '|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest();path=WORK/(key+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        body,meta=fetch('klines',contract,day);bars=minute_bars(body,day);del body
        old={(a['kind'],a['day']):a['sha256'] for a in old_archives};assert old[('klines',day)]==meta['sha256']
        archives=[meta];dates=[day]
        if needs_next:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        blocks={e['observation_id']:{'aggTrades':[],'trades':[]} for e in events}
        for when in dates:
          for kind in ('aggTrades','trades'):
            body,meta=fetch(kind,contract,when);archives.append(meta)
            if kind=='aggTrades':assert old[(kind,when)]==meta['sha256']
            for chunk in pd.read_csv(io.BytesIO(body),compression='zip',chunksize=150_000):
                if kind=='trades':
                    idcol='id' if 'id' in chunk.columns else 'trade_id';qtycol='qty' if 'qty' in chunk.columns else 'quantity'
                    chunk=chunk.rename(columns={'time':'transact_time',idcol:'agg_trade_id',qtycol:'quantity'})
                needed=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
                if not set(needed).issubset(chunk.columns):raise ValueError('unexpected_trade_columns')
                t=chunk.transact_time.to_numpy('int64')
                for e in events:
                    z=chunk.loc[(t>=int(e['trigger_minute']))&(t<int(e['quarter_end'])+M),needed]
                    if len(z):blocks[e['observation_id']][kind].append(z)
            del body
        rows=[]
        for e in events:
            b=blocks[e['observation_id']]
            if not b['trades'] or not b['aggTrades']:
                rows.append({'observation_id':e['observation_id'],'reconciled':False,'reason':'missing_trade_tape'});continue
            agg=pd.concat(b['aggTrades'],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            raw=pd.concat(b['trades'],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            rows.append({'observation_id':e['observation_id'],**reconcile(e,agg,raw,bars)})
        out={'contract':contract,'day':day,'needs_next':needs_next,'status':'verified','archives':archives,'rows':rows}
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path)
        return out
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:140]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs_next,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'reconciled':False,'reason':'archive_error'} for e in events]}
def main():
    candidates=pd.read_parquet(SOURCE).set_index('observation_id');tasks=[];seen=set()
    for file in sorted(ORIGINAL.glob('*.json')):
        r=json.loads(file.read_text(encoding='utf-8'))
        if r.get('status')!='verified':continue
        ids=[x['observation_id'] for x in r['rows'] if x['status']=='minute_trade_ohlc_mismatch' and x['observation_id'] not in seen]
        if not ids:continue
        seen.update(ids);events=[]
        for obs in ids:
            e=candidates.loc[obs].to_dict();e['observation_id']=obs;events.append(e)
        tasks.append((r['contract'],r['day'],r['needs_next'],events,r['archives']))
    # Archive-size ordering is independent of trade outcomes and lets smaller
    # source checks complete before the largest daily files.
    tasks.sort(key=lambda s:sum(a.get('bytes',0) for a in s[4]))
    print('UNIVERSE33_RAW_BATCH_TASKS',len(tasks),'mismatch_events',len(seen),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fs=[pool.submit(task,s) for s in tasks]
        for f in concurrent.futures.as_completed(fs):
            results.append(f.result())
            if len(results)%5==0:print('UNIVERSE33_RAW_BATCH',len(results),'/',len(tasks),flush=True)
    rows=[x for r in results for x in r['rows']];reason=Counter(x.get('reason','reconciled') for x in rows)
    out={'batch_tasks':len(tasks),'mismatch_events':len(seen),'reconciled_events':sum(x.get('reconciled',False) for x in rows),
         'unresolved_reasons':dict(reason),'archive_errors':[r for r in results if r['status']!='verified'],
         'strict_protocol_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
         'note':'Completed checkpoints at batch start only; unreconciled events remain data-quality failures.'}
    (HERE/'原始成交批次复核进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_RAW_BATCH_COMPLETE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
