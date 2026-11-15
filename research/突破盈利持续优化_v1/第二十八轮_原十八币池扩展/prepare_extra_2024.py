"""Stream verified 2024 monthly archives for the seven additional contracts."""
import concurrent.futures,hashlib,io,json,os,shutil,threading,time
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
OUT=ROOT/'work'/'breakout_2024_expanded18'/'normalized';OUT.mkdir(parents=True,exist_ok=True)
OLD=ROOT/'work'/'breakout_2024_11'/'normalized'
EXTRA=['ZECUSDT','TAOUSDT','TRXUSDT','1000PEPEUSDT','PAXGUSDT','SUIUSDT','FETUSDT']
OLD11=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
MONTHS=[f'2024-{m:02}' for m in range(1,7)];BASE='https://data.binance.vision/data/futures/um/monthly'
MIN_FREE=1_900_000_000;local=threading.local()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def fetch(kind,contract,month):
    sub=f'{kind}/{contract}'+('/1m' if kind!='fundingRate' else '')
    suffix='fundingRate' if kind=='fundingRate' else '1m';name=f'{contract}-{suffix}-{month}.zip'
    url=f'{BASE}/{sub}/{name}';error='unknown'
    for attempt in range(3):
      try:
        if shutil.disk_usage(OUT).free<MIN_FREE:raise RuntimeError('insufficient_disk_reserve')
        ch=session().get(url+'.CHECKSUM',timeout=(12,45))
        if ch.status_code==404:return None,{'kind':kind,'contract':contract,'month':month,'status':'checksum_404_missing'}
        ch.raise_for_status();sha=ch.text.strip().split()[0].lower()
        if len(sha)!=64:raise ValueError('invalid_checksum')
        response=session().get(url,timeout=(12,120));response.raise_for_status();body=response.content
        if hashlib.sha256(body).hexdigest()!=sha:raise ValueError('checksum_mismatch')
        d=pd.read_csv(io.BytesIO(body),compression='zip')
        if kind=='fundingRate':
            wanted=['calc_time','funding_interval_hours','last_funding_rate'];rename={'calc_time':'ts'}
        else:
            wanted=['open_time','open','high','low','close']
            if kind=='klines':wanted+=['volume','quote_volume','count','taker_buy_quote_volume']
            rename={'open_time':'ts','count':'trade_count'}
        if not set(wanted)<=set(d.columns):raise ValueError('unexpected_columns')
        d=d[wanted].rename(columns=rename)
        for col in d.columns:d[col]=pd.to_numeric(d[col],errors='coerce')
        if d.ts.isna().any():raise ValueError('invalid_timestamp')
        d.ts=d.ts.astype('int64')
        start=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)
        end=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        if not d.ts.between(start,end-1).all() or d.ts.duplicated().any():raise ValueError('invalid_month_or_duplicates')
        if kind!='fundingRate' and not (d.ts%60_000==0).all():raise ValueError('invalid_minute_grid')
        if kind=='fundingRate' and (not np.isfinite(d[['funding_interval_hours','last_funding_rate']].to_numpy()).all() or (d.funding_interval_hours<=0).any()):
            raise ValueError('invalid_funding')
        expected=(end-start)//60_000 if kind!='fundingRate' else None
        return d,{'kind':kind,'contract':contract,'month':month,'status':'verified','sha256':sha,'bytes':len(body),
                  'rows':len(d),'expected_minutes':int(expected) if expected is not None else None,
                  'missing_minutes':int(expected-len(d)) if expected is not None else None}
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:100]
        if 'insufficient_disk_reserve' in error:break
        if attempt<2:time.sleep(1+attempt)
    return None,{'kind':kind,'contract':contract,'month':month,'status':'error','error':error}
def contract_task(c):
    records=[]
    for kind in ('klines','markPriceKlines','fundingRate'):
        pieces=[]
        for month in (['2023-12',*MONTHS] if kind=='klines' else MONTHS):
            d,rec=fetch(kind,c,month);records.append(rec)
            if d is not None:pieces.append(d)
        if any(x['status']=='error' for x in records):return {'contract':c,'status':'error','records':records}
        cols=(['ts','funding_interval_hours','last_funding_rate'] if kind=='fundingRate' else
              ['ts','open','high','low','close','volume','quote_volume','trade_count','taker_buy_quote_volume'] if kind=='klines' else
              ['ts','open','high','low','close'])
        data=(pd.concat(pieces,ignore_index=True).sort_values('ts').reset_index(drop=True) if pieces else
              pd.DataFrame({k:pd.Series(dtype='int64' if k=='ts' else 'float64') for k in cols}))
        if data.ts.duplicated().any():raise ValueError('duplicate_normalized')
        if shutil.disk_usage(OUT).free<MIN_FREE:raise RuntimeError('insufficient_disk_reserve')
        data.to_parquet(OUT/f'{c}_{kind}.parquet',index=False)
    return {'contract':c,'status':'verified_or_recorded_absent','records':records}
def main():
    linked=[]
    for c in OLD11:
      for kind in ('klines','markPriceKlines','fundingRate'):
        src=OLD/f'{c}_{kind}.parquet';dst=OUT/src.name
        if not src.exists():raise FileNotFoundError(str(src))
        if not dst.exists():
            try:os.link(src,dst);method='hardlink'
            except OSError:
                if shutil.disk_usage(OUT).free-src.stat().st_size<MIN_FREE:raise RuntimeError('insufficient_disk_reserve')
                shutil.copy2(src,dst);method='copy'
        else:
            method='existing'
            if not os.path.samefile(src,dst) and hashlib.sha256(src.read_bytes()).digest()!=hashlib.sha256(dst.read_bytes()).digest():
                raise ValueError('existing_file_content_mismatch')
        if dst.stat().st_size!=src.stat().st_size:raise ValueError('reused_file_size_mismatch')
        linked.append({'file':src.name,'method':method,'bytes':src.stat().st_size})
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(contract_task,c) for c in EXTRA]
        for future in concurrent.futures.as_completed(futures):
            try:r=future.result()
            except Exception as exc:r={'status':'error','error':type(exc).__name__+':'+str(exc)[:100],'records':[]}
            results.append(r);print('EXPANDED2024_CONTRACT',r.get('contract'),r['status'],flush=True)
    records=[x for r in results for x in r.get('records',[])]
    summary={'contracts':EXTRA,'verified_records':sum(x['status']=='verified' for x in records),
        'missing_404':[x for x in records if x['status']=='checksum_404_missing'],
        'errors':[r for r in results if r['status']=='error']+[x for x in records if x['status']=='error'],
        'records':records,'reused_existing_files':linked,'bytes_downloaded':sum(x.get('bytes',0) for x in records),
        'disk_free_bytes':shutil.disk_usage(OUT).free,'disk_reserve_bytes':MIN_FREE,
        'note':'404 is recorded as missing coverage, not asserted to prove non-listing; no missing-price imputation.'}
    (HERE/'新增七币2024档案校验.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXPANDED2024_PREP_COMPLETE',json.dumps({k:summary[k] for k in ['verified_records','missing_404','errors','bytes_downloaded','disk_free_bytes']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
