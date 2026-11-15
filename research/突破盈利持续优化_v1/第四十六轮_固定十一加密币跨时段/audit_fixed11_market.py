"""Compare BTC/ETH 1m and 15m archives with the fixed-pool market inputs."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;M=60_000;Q=15*M
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def readzip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist();assert len(names)==1;raw=z.read(names[0]);header=raw.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
    return pd.read_csv(io.BytesIO(raw),header=0 if header else None,names=None if header else COLS)
def fetch(session,url):
    c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();expected=c.text.strip().split()[0].lower()
    r=session.get(url,timeout=(15,90));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==expected
    return readzip(r.content),expected
def main():
    samples={2024:[('BTCUSDT','2024-02-15 12:00'),('ETHUSDT','2024-03-15 12:00'),('BTCUSDT','2024-05-15 12:00'),('ETHUSDT','2024-06-15 12:00')],
             2026:[('BTCUSDT','2026-05-15 12:00'),('ETHUSDT','2026-05-20 12:00'),('BTCUSDT','2026-06-15 12:00'),('ETHUSDT','2026-07-15 12:00')]}
    s=requests.Session()
    for year,choices in samples.items():
        out=H/str(year);bars=pd.read_parquet(out/'BTC_ETH一分钟合成十五分钟.parquet').set_index(['symbol','open_time']);results=[]
        root=ROOT/'work'/('breakout_2024_11' if year==2024 else 'breakout_forward_2026')/'normalized'
        for sym,date in choices:
            t=int(pd.Timestamp(date,tz='UTC').timestamp()*1000);day=date[:10];month=date[:7]
            u=f'https://data.binance.vision/data/futures/um/daily/klines/{sym}/1m/{sym}-1m-{day}.zip'
            d,ds=fetch(s,u);d=d[d.open_time.between(t,t+Q-1)].sort_values('open_time');assert len(d)==15 and list(d.open_time)==list(range(t,t+Q,M))
            norm=pd.read_parquet(root/f'{sym}_klines.parquet');norm=norm[norm.ts.between(t,t+Q-1)].sort_values('ts');assert len(norm)==15
            for a,b in [('open','open'),('high','high'),('low','low'),('close','close'),('volume','volume'),('quote_volume','quote_volume'),('count','trade_count')]:
                assert np.allclose(d[a].to_numpy(float),norm[b].to_numpy(float),rtol=1e-10,atol=1e-12),(sym,date,a)
            u=f'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/15m/{sym}-15m-{month}.zip'
            z,zs=fetch(s,u);z=z[z.open_time.eq(t)];assert len(z)==1;z=z.iloc[0];b=bars.loc[(sym,t)]
            a=[float(d.open.iloc[0]),float(d.high.max()),float(d.low.min()),float(d.close.iloc[-1])]
            assert np.allclose(a,[z.open,z.high,z.low,z.close],rtol=1e-9,atol=1e-12)
            assert np.allclose(a,[b.open,b.high,b.low,b.close],rtol=1e-9,atol=1e-12)
            assert int(d['count'].sum())==int(z['count'])==int(b['count'])
            results.append({'symbol':sym,'time':date,'daily_minute_sha256':ds,'monthly_quarter_sha256':zs})
            print('FIXED11_46_MARKET_SAMPLE',year,len(results),'/',len(choices),flush=True)
        x={'year':year,'sample_count':len(results),'all_checks_pass':True,'samples':results,
           'note':'Same-exchange archive samples; future-bar perturbation is checked separately.'}
        (out/'BTC_ETH行情样本核验.json').write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
