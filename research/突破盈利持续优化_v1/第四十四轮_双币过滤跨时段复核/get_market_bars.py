"""Retrieve past BTC/ETH 15-minute bars and trade counts for training events."""
import concurrent.futures,hashlib,io,json,shutil,threading,time,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;W=ROOT/'work'/'dual44'/'bars';W.mkdir(parents=True,exist_ok=True)
Q=900_000;MIN_FREE=1_900_000_000;local=threading.local()
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
FP=hashlib.sha256(Path(__file__).read_bytes()+(H/'冻结研究方案.md').read_bytes()+(H/'冻结输入'/'baseline_signal.parquet').read_bytes()).hexdigest()
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(z):
    symbol,month,times=z;key=hashlib.sha256((FP+'|'+symbol+'|'+month+'|'+','.join(map(str,times))).encode()).hexdigest();path=W/(key+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    url=f'https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/15m/{symbol}-15m-{month}.zip';error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        c=session().get(url+'.CHECKSUM',timeout=(15,50))
        if c.status_code==404:return {'symbol':symbol,'month':month,'status':'checksum_404','rows':[]}
        c.raise_for_status();sha=c.text.strip().split()[0].lower();r=session().get(url,timeout=(15,90));r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('checksum_mismatch')
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names=z.namelist();assert len(names)==1;raw=z.read(names[0]);header=raw.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
        d=pd.read_csv(io.BytesIO(raw),header=0 if header else None,names=None if header else COLS)
        cols=['open_time','open','high','low','close','volume','close_time','count']
        if not set(cols).issubset(d.columns):raise ValueError('column_schema')
        d=d[cols].apply(pd.to_numeric,errors='raise')
        if not np.isfinite(d.to_numpy(float)).all() or d.open_time.duplicated().any():raise ValueError('nonfinite_or_duplicate')
        lo=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000);hi=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        if not d.open_time.between(lo,hi-1).all() or (d.open_time%Q!=0).any() or (d.close_time!=d.open_time+Q-1).any():raise ValueError('time')
        if not (d[['open','high','low','close']]>0).all().all() or (d['count']<0).any() or (d['count']%1!=0).any():raise ValueError('price_or_count')
        if (d.high<d[['open','low','close']].max(axis=1)).any() or (d.low>d[['open','high','close']].min(axis=1)).any():raise ValueError('ohlc')
        d=d[d.open_time.isin(times)];out={'symbol':symbol,'month':month,'status':'verified','sha256':sha,'bytes':len(r.content),'rows':d.to_dict('records')}
        tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path);return out
      except Exception as e:
        error=type(e).__name__+':'+str(e)[:120]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'symbol':symbol,'month':month,'status':'error','error':error,'rows':[]}
def main():
    frozen=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()==frozen['plan_sha256']
    source=H/'冻结输入'/'baseline_signal.parquet';assert hashlib.sha256(source.read_bytes()).hexdigest()==frozen['inputs']['baseline_signal.parquet']
    d=pd.read_parquet(source);needed=sorted({int(q)-i*Q for q in d.quarter_start for i in range(1,22)})
    grouped={}
    for t in needed:grouped.setdefault(pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m'),[]).append(t)
    tasks=[(s,m,times) for s in ('BTCUSDT','ETHUSDT') for m,times in sorted(grouped.items())];result=[]
    print('CROSS44_BAR_TASKS',len(tasks),'required_distinct_quarters',len(needed),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for f in concurrent.futures.as_completed([pool.submit(task,t) for t in tasks]):
            result.append(f.result());print('CROSS44_BARS',len(result),'/',len(tasks),flush=True)
    rows=[{'symbol':r['symbol'],**x} for r in result for x in r['rows']]
    columns=['symbol','open_time','open','high','low','close','volume','close_time','count'];bars=pd.DataFrame(rows,columns=columns)
    assert not bars.duplicated(['symbol','open_time']).any();bars.to_parquet(H/'BTC_ETH过去十五分钟数据.parquet',index=False)
    out={'requested_archives':len(tasks),'verified_archives':sum(r['status']=='verified' for r in result),
         'archive_errors':[r for r in result if r['status']!='verified'],'bar_rows':len(bars),
         'archives':[{k:v for k,v in r.items() if k!='rows'} for r in result],
         'note':'Prior closed 15-minute bars only. Archive SHA and OHLC are source checks, not real-time availability proof.'}
    (H/'BTC_ETH行情来源质量.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CROSS44_BARS_COMPLETE',json.dumps({k:v for k,v in out.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
