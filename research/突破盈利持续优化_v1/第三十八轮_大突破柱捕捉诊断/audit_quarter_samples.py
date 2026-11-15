"""Rebuild five deterministic public 15-minute bars from daily 1-minute bars."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;Q=900_000;M=60_000
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def main():
    d=pd.read_parquet(HERE/'冻结输入'/'baseline_signal.parquet').sort_values(['contract','quarter_start']).reset_index(drop=True)
    bars=pd.read_parquet(HERE/'候选十五分钟行情.parquet').set_index(['contract','open_time'])
    selected=[]
    for ix in np.linspace(0,len(d)-1,5,dtype=int):
        r=d.iloc[int(ix)];key=(r.contract,int(r.quarter_start))
        if key in bars.index and key not in selected:selected.append(key)
    assert len(selected)>=4
    s=requests.Session();out=[]
    for contract,ts in selected:
      date=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m-%d');name=f'{contract}-1m-{date}.zip'
      url=f'https://data.binance.vision/data/futures/um/daily/klines/{contract}/1m/{name}'
      try:
        c=s.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
        r=s.get(url,timeout=(15,90));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names=z.namelist();assert len(names)==1;raw=z.read(names[0]);header=raw.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
        m=pd.read_csv(io.BytesIO(raw),header=0 if header else None,names=None if header else COLS)
        m=m[m.open_time.between(ts,ts+Q-1)].sort_values('open_time')
        assert len(m)==15 and list(m.open_time)==list(range(ts,ts+Q,M))
        x=[float(m.open.iloc[0]),float(m.high.max()),float(m.low.min()),float(m.close.iloc[-1])]
        b=bars.loc[(contract,ts)];official=[float(b.open),float(b.high),float(b.low),float(b.close)]
        ok=bool(np.allclose(x,official,rtol=1e-9,atol=1e-12))
        out.append({'contract':contract,'quarter_start':ts,'day':date,'status':'verified' if ok else 'ohlc_mismatch',
                    'minute_sha256':sha,'ohlc_from_minutes':x,'monthly_quarter_ohlc':official})
      except Exception as e:
        out.append({'contract':contract,'quarter_start':ts,'day':date,'status':'error','error':type(e).__name__+':'+str(e)[:120]})
      print('CAPTURE38_SAMPLE',len(out),'/',len(selected),flush=True)
    result={'samples':out,'sample_count':len(out),'sample_pass':sum(x['status']=='verified' for x in out),
            'note':'A deterministic sample only; both timeframes originate from the same public exchange archives.'}
    (HERE/'十五分钟行情样本独立核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE38_SAMPLE_COMPLETE',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
