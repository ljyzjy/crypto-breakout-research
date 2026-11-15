"""Reconcile one recorded OHLC mismatch using official raw and aggregate trades."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
SYMBOL='ADAUSDT';DAY='2024-03-04';MINUTE=1_709_532_900_000
BASE='https://data.binance.vision/data/futures/um/daily/'
def fetch(kind):
    if kind=='klines':key=f'klines/{SYMBOL}/1m/{SYMBOL}-1m-{DAY}.zip'
    else:key=f'{kind}/{SYMBOL}/{SYMBOL}-{kind}-{DAY}.zip'
    c=requests.get(BASE+key+'.CHECKSUM',timeout=(15,60));c.raise_for_status();sha=c.text.strip().split()[0]
    r=requests.get(BASE+key,timeout=(15,120));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha
    return r.content,sha
def rows(body,time_col):
    keep=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',chunksize=200_000):
        part=chunk[(chunk[time_col]>=MINUTE)&(chunk[time_col]<MINUTE+60_000)]
        if len(part):keep.append(part)
    return pd.concat(keep,ignore_index=True)
def main():
    candidates=pd.read_parquet(PARENT/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet')
    e=candidates[(candidates.symbol==SYMBOL)&(candidates.trigger_minute==MINUTE)].iloc[0]
    k,ks=fetch('klines');bar=pd.read_csv(io.BytesIO(k),compression='zip').set_index('open_time').loc[MINUTE]
    a,sha_a=fetch('aggTrades');agg=rows(a,'transact_time').sort_values(['transact_time','agg_trade_id'])
    raw,sha_r=fetch('trades');d=rows(raw,'time')
    if 'id' in d.columns:d=d.sort_values(['time','id'])
    else:d=d.sort_values('time')
    def summary(frame,time_col):
        prices=frame.price.to_numpy(float);t=frame[time_col].to_numpy(np.int64)
        cross=np.flatnonzero((prices>e.upper)|(prices<e.lower))
        return {'records':len(frame),'ohlc':[float(prices[0]),float(prices.max()),float(prices.min()),float(prices[-1])],
                'first_time':int(t[0]),'first_cross_time':int(t[cross[0]]) if len(cross) else None,
                'first_cross_price':float(prices[cross[0]]) if len(cross) else None}
    out={'symbol':SYMBOL,'day':DAY,'minute':MINUTE,'upper':float(e.upper),'lower':float(e.lower),
         'kline_ohlc':[float(bar.open),float(bar.high),float(bar.low),float(bar.close)],
         'previous_kline_close':float(pd.read_csv(io.BytesIO(k),compression='zip').set_index('open_time').loc[MINUTE-60_000,'close']),
         'aggregate':summary(agg,'transact_time'),'raw':summary(d,'time'),
         'archive_sha256':{'kline':ks,'aggregate':sha_a,'raw':sha_r},
         'note':'Single source reconciliation; do not infer all mismatches behave the same.'}
    (HERE/'一分钟数据冲突个案复核.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_MISMATCH_SAMPLE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
