"""Rebuild four deterministic BTC/ETH 15m OHLC/trade counts from daily 1m files."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;Q=900_000;M=60_000
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def main():
    bars=pd.read_parquet(H/'BTC_ETH过去十五分钟数据.parquet');samples=[];session=requests.Session();choices=[]
    for symbol in ('BTCUSDT','ETHUSDT'):
        g=bars[bars.symbol.eq(symbol)].sort_values('open_time').reset_index(drop=True)
        for i in (len(g)//4,3*len(g)//4):choices.append(g.iloc[i])
    for bar in choices:
      t=int(bar.open_time);day=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d');sym=bar.symbol
      url=f'https://data.binance.vision/data/futures/um/daily/klines/{sym}/1m/{sym}-1m-{day}.zip'
      try:
        c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
        r=session.get(url,timeout=(15,90));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names=z.namelist();assert len(names)==1;raw=z.read(names[0]);header=raw.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
        d=pd.read_csv(io.BytesIO(raw),header=0 if header else None,names=None if header else COLS)
        d=d[d.open_time.between(t,t+Q-1)].sort_values('open_time');assert len(d)==15 and list(d.open_time)==list(range(t,t+Q,M))
        a=[float(d.open.iloc[0]),float(d.high.max()),float(d.low.min()),float(d.close.iloc[-1])]
        b=[float(bar.open),float(bar.high),float(bar.low),float(bar.close)]
        count=int(d['count'].sum());ok=bool(np.allclose(a,b,rtol=1e-9,atol=1e-12) and count==int(bar['count']))
        samples.append({'symbol':sym,'open_time':t,'day':day,'status':'verified' if ok else 'minute_mismatch',
                        'daily_minute_sha256':sha,'minute_ohlc':a,'quarter_ohlc':b,'minute_count_sum':count,'quarter_count':int(bar['count'])})
      except Exception as e:
        samples.append({'symbol':sym,'open_time':t,'day':day,'status':'error','error':type(e).__name__+':'+str(e)[:120]})
      print('DUAL42_SAMPLE',len(samples),'/',len(choices),flush=True)
    out={'sample_count':len(samples),'sample_verified':sum(x['status']=='verified' for x in samples),'samples':samples,
         'note':'Both timeframe archives are from the same exchange; this is a four-sample aggregation check.'}
    (H/'BTC_ETH一分钟样本核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL42_SAMPLE_COMPLETE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
