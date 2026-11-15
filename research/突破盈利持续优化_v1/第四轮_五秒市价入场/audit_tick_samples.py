"""Recompute deterministic sample of 5-second excerpts from original archives."""
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
files=sorted(HERE.glob('五秒价格摘要_*.parquet'))
assert files
all_ticks=pd.concat([pd.read_parquet(p) for p in files],ignore_index=True)
all_ticks=all_ticks[all_ticks.status.eq('verified')].sort_values(['source_year','contract','decision_ts']).reset_index(drop=True)
assert len(all_ticks)>0
indices=np.unique(np.linspace(0,len(all_ticks)-1,min(8,len(all_ticks)),dtype=int))
sample=all_ticks.iloc[indices];checked=[]
for r in sample.itertuples(index=False):
    name=f'{r.contract}-aggTrades-{r.day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{r.contract}/{name}'
    response=requests.get(url,timeout=(12,120));response.raise_for_status();body=response.content
    assert hashlib.sha256(body).hexdigest()==r.archive_sha256
    chunks=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['price','transact_time'],chunksize=200_000):
        part=chunk[chunk.transact_time.ge(r.decision_ts+5_000)&chunk.transact_time.lt(r.decision_ts+60_000)]
        if len(part):chunks.append(part)
    d=pd.concat(chunks,ignore_index=True).sort_values('transact_time',kind='mergesort')
    assert len(d)==r.suffix_trade_count
    assert int(d.transact_time.iloc[0])==r.entry_exec_ts and int(d.transact_time.iloc[-1])==r.suffix_last_ts
    assert np.isclose(float(d.price.iloc[0]),r.raw_entry_5s,rtol=1e-12)
    assert np.isclose(float(d.price.max()),r.suffix_high,rtol=1e-12)
    assert np.isclose(float(d.price.min()),r.suffix_low,rtol=1e-12)
    assert np.isclose(float(d.price.iloc[-1]),r.suffix_close,rtol=1e-12)
    checked.append({'observation_id':r.observation_id,'contract':r.contract,'day':r.day,'trades_after_5s':len(d)})
    print('TICK_SAMPLE_OK',r.contract,r.day,flush=True)
report={'sampled_events':len(checked),'checked':checked,
        'limits':'The sample checks public trade extraction, not the actual fill, market impact or order-book state.'}
(HERE/'五秒逐笔独立抽查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TICK_SAMPLE_AUDIT_PASS',len(checked),flush=True)
