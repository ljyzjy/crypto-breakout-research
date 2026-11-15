"""Independently reread sampled later-minute tapes for 5-second taker notionals."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
sig=pd.read_parquet(PARENT/'第六轮_柱内首次触价'/'逐笔首次触价与五秒入场_训练.parquet')
sig=sig[sig.status.eq('verified')].set_index('observation_id')
ft=pd.read_parquet(HERE/'后续分钟五秒主动成交特征.parquet').set_index('observation_id')
avail=ft[ft.status.eq('verified')].sort_index()
chosen=avail.iloc[np.unique(np.linspace(0,len(avail)-1,min(3,len(avail)),dtype=int))];samples=[]
for ix,x in chosen.iterrows():
    r=sig.loc[ix];name=f'{r.contract}-aggTrades-{r.day}.zip'
    u=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{r.contract}/{name}'
    response=requests.get(u,timeout=(12,120));response.raise_for_status();body=response.content
    assert hashlib.sha256(body).hexdigest()==x.archive_sha256
    parts=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['price','quantity','transact_time','is_buyer_maker'],dtype={'is_buyer_maker':str},chunksize=200_000):
        take=chunk[chunk.transact_time.gt(r.decision_ts)&chunk.transact_time.lt(r.decision_ts+5000)]
        if len(take):parts.append(take)
    tape=pd.concat(parts,ignore_index=True);value=tape.price.to_numpy(float)*tape.quantity.to_numpy(float)
    maker=tape.is_buyer_maker.str.lower();buy=float(value[maker.eq('false').to_numpy()].sum());sell=float(value[maker.eq('true').to_numpy()].sum())
    assert len(tape)==x['count'] and np.isclose(buy,x.buy_notional,rtol=1e-11) and np.isclose(sell,x.sell_notional,rtol=1e-11)
    samples.append({'id':ix,'contract':r.contract,'day':r.day});print('CROSSFLOW_SAMPLE_OK',r.contract,r.day,flush=True)
out={'archive_samples':samples,'count':len(samples)}
(HERE/'后续分钟逐笔样本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('LATERFLOW_SAMPLE_PASS',len(samples),flush=True)
