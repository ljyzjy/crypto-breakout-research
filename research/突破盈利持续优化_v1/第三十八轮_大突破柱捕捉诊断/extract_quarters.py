"""Recover checksum-verified 15-minute bars only for frozen candidate quarters."""
import concurrent.futures,hashlib,io,json,shutil,threading,time,zipfile
from pathlib import Path
import numpy as np,pandas as pd,psutil,requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;WORK=ROOT/'work'/'capture38'/'quarters';WORK.mkdir(parents=True,exist_ok=True)
SOURCE=HERE/'冻结输入'/'baseline_signal.parquet';PLAN=HERE/'事后诊断方案.md';M=60_000;Q=15*M;MIN_FREE=1_900_000_000
FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+PLAN.read_bytes()+SOURCE.read_bytes()).hexdigest();local=threading.local()
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(spec):
    symbol,month,times=spec;key=hashlib.sha256((FINGERPRINT+'|'+symbol+'|'+month+'|'+','.join(map(str,times))).encode()).hexdigest();path=WORK/(key+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    name=f'{symbol}-15m-{month}.zip';url=f'https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/15m/{name}';error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<700*1024**2:time.sleep(3)
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        c=session().get(url+'.CHECKSUM',timeout=(15,50))
        if c.status_code==404:return {'symbol':symbol,'month':month,'status':'checksum_404','rows':[]}
        c.raise_for_status();sha=c.text.strip().split()[0].lower();r=session().get(url,timeout=(15,90));r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('sha256_mismatch')
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names=z.namelist();assert len(names)==1 and names[0].endswith('.csv')
            data=z.read(names[0]);has_header=data.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
        d=pd.read_csv(io.BytesIO(data),header=0 if has_header else None,names=None if has_header else COLS)
        required=['open_time','open','high','low','close','volume','close_time']
        if not set(required).issubset(d.columns):raise ValueError('column_schema')
        d=d[required].apply(pd.to_numeric,errors='raise')
        if not np.isfinite(d.to_numpy(float)).all() or d.open_time.duplicated().any():raise ValueError('nonfinite_or_duplicate')
        lo=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000);hi=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        if not d.open_time.between(lo,hi-1).all() or (d.open_time%Q!=0).any() or (d.close_time!=d.open_time+Q-1).any():raise ValueError('bar_time')
        if not (d[['open','high','low','close']]>0).all().all():raise ValueError('bad_price')
        if (d.high<d[['open','low','close']].max(axis=1)).any() or (d.low>d[['open','high','close']].min(axis=1)).any():raise ValueError('bad_ohlc')
        d=d[d.open_time.isin(times)]
        out={'symbol':symbol,'month':month,'status':'verified','sha256':sha,'bytes':len(r.content),'rows':d.to_dict('records')}
        tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path)
        return out
      except Exception as e:
        error=type(e).__name__+':'+str(e)[:120]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'symbol':symbol,'month':month,'status':'error','error':error,'rows':[]}
def main():
    frozen=json.loads((HERE/'冻结输入哈希.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256']==hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert frozen['sources']['baseline_signal.parquet']['sha256']==hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    d=pd.read_parquet(SOURCE);assert d.observation_id.is_unique
    d['month']=pd.to_datetime(d.quarter_start,unit='ms',utc=True).dt.strftime('%Y-%m')
    tasks=[(s,m,sorted(set(map(int,g.quarter_start)))) for (s,m),g in d.groupby(['contract','month'])]
    tasks.sort(key=lambda x:(x[1],x[0]));print('CAPTURE38_QUARTER_TASKS',len(tasks),'candidates',len(d),flush=True);result=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fs=[pool.submit(task,x) for x in tasks]
        for f in concurrent.futures.as_completed(fs):
            result.append(f.result())
            if len(result)%20==0:print('CAPTURE38_QUARTERS',len(result),'/',len(tasks),flush=True)
    rows=[{'contract':r['symbol'],'month':r['month'],**z} for r in result for z in r['rows']]
    bars=pd.DataFrame(rows,columns=['contract','month','open_time','open','high','low','close','volume','close_time'])
    assert not bars.duplicated(['contract','open_time']).any()
    bars.to_parquet(HERE/'候选十五分钟行情.parquet',index=False)
    manifest={'candidate_events':len(d),'archive_tasks':len(tasks),'verified_archives':sum(x['status']=='verified' for x in result),
              'unavailable_archives':[x for x in result if x['status']!='verified'],
              'bar_rows':len(bars),'archives':[{k:v for k,v in x.items() if k!='rows'} for x in result],
              'fingerprint':FINGERPRINT,'note':'Post-close bars are labels only, not real-time strategy inputs.'}
    (HERE/'十五分钟行情来源质量.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE38_QUARTERS_COMPLETE',json.dumps({k:v for k,v in manifest.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
