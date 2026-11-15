"""Check local BTC/ETH minute inputs against source and official 15m samples."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;Q=900_000;M=60_000
RAW=ROOT/'work'/'breakout_2023_11'/'raw'/'klines';NORM=ROOT/'work'/'breakout_2023_11'/'normalized'
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def csvzip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist();assert len(names)==1;raw=z.read(names[0]);header=raw.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
    return pd.read_csv(io.BytesIO(raw),header=0 if header else None,names=None if header else COLS)
def main():
    candidates=[('BTCUSDT','2023-02-15 12:00'),('ETHUSDT','2023-05-15 12:00'),
                ('BTCUSDT','2023-08-15 12:00'),('ETHUSDT','2023-11-15 12:00')]
    bars=pd.read_parquet(H/'BTC_ETH一分钟合成十五分钟.parquet').set_index(['symbol','open_time'])
    manifest=json.loads((P/'第二轮_成本空间与即时成交'/'2023公开档案校验清单.json').read_text(encoding='utf-8'))
    sample=[];session=requests.Session()
    for sym,date in candidates:
      t=int(pd.Timestamp(date,tz='UTC').timestamp()*1000);month=date[:7]
      try:
        local=RAW/sym/f'{sym}-1m-{month}.zip';expected=next(x['sha256'] for x in manifest['records'] if x['kind']=='klines' and x['contract']==sym and x['month']==month)
        content=local.read_bytes();assert hashlib.sha256(content).hexdigest()==expected
        minute=csvzip(content);minute=minute[minute.open_time.between(t,t+Q-1)].sort_values('open_time')
        assert len(minute)==15 and list(minute.open_time)==list(range(t,t+Q,M))
        norm=pd.read_parquet(NORM/f'{sym}_klines.parquet');norm=norm[norm.ts.between(t,t+Q-1)].sort_values('ts')
        assert len(norm)==15 and list(norm.ts)==list(range(t,t+Q,M))
        for a,b in [('open','open'),('high','high'),('low','low'),('close','close'),('volume','volume'),('quote_volume','quote_volume'),('count','trade_count')]:
            assert np.allclose(minute[a].to_numpy(float),norm[b].to_numpy(float),rtol=1e-10,atol=1e-12),(sym,date,a)
        url=f'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/15m/{sym}-15m-{month}.zip'
        c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();official_sha=c.text.strip().split()[0].lower()
        r=session.get(url,timeout=(15,90));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==official_sha
        quarter=csvzip(r.content);q=quarter[quarter.open_time.eq(t)];assert len(q)==1;q=q.iloc[0]
        localq=bars.loc[(sym,t)];a=[float(minute.open.iloc[0]),float(minute.high.max()),float(minute.low.min()),float(minute.close.iloc[-1])]
        b=[float(q.open),float(q.high),float(q.low),float(q.close)];n=int(minute['count'].sum())
        assert np.allclose(a,b,rtol=1e-9,atol=1e-12) and n==int(q['count'])
        assert np.allclose(a,[localq.open,localq.high,localq.low,localq.close],rtol=1e-9,atol=1e-12) and n==int(localq['count'])
        sample.append({'symbol':sym,'open_time':t,'status':'verified','local_minute_sha256':expected,
                       'official_quarter_sha256':official_sha,'ohlc':a,'trade_count':n})
      except Exception as e:sample.append({'symbol':sym,'open_time':t,'status':'error','error':type(e).__name__+':'+str(e)[:130]})
      print('OLD11_2023_MARKET_SAMPLE',len(sample),'/',len(candidates),flush=True)
    out={'sample_count':len(sample),'verified':sum(x['status']=='verified' for x in sample),'samples':sample,
         'note':'Four samples across BTC/ETH and dates; same-exchange source archive checks, not a full audit.'}
    (H/'BTC_ETH_2023行情样本核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_MARKET_SAMPLE_COMPLETE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
