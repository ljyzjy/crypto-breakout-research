"""Re-read public archive samples to verify first crossing and delayed execution."""
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
d=pd.read_parquet(HERE/'逐笔首次触价与五秒入场_训练.parquet')
d=d[d.status.eq('verified')].sort_values(['source_year','contract','trigger_minute']).reset_index(drop=True)
sample=d.iloc[np.unique(np.linspace(0,len(d)-1,min(6,len(d)),dtype=int))]
checked=[]
for r in sample.itertuples(index=False):
    name=f'{r.contract}-aggTrades-{r.day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{r.contract}/{name}'
    response=requests.get(url,timeout=(12,120));response.raise_for_status();body=response.content
    assert hashlib.sha256(body).hexdigest()==r.archive_sha256
    chunks=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=200_000):
        part=chunk[chunk.transact_time.ge(r.trigger_minute)&chunk.transact_time.lt(min(r.trigger_minute+120_000,r.quarter_end))]
        if len(part):chunks.append(part)
    ticks=pd.concat(chunks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort').reset_index(drop=True)
    before=ticks[ticks.transact_time.lt(r.trigger_minute+60_000)]
    crossed=before[(before.price>r.upper)|(before.price<r.lower)]
    first=crossed.iloc[0];side=1 if first.price>r.upper else -1
    assert int(first.transact_time)==r.decision_ts and side==r.side and np.isclose(first.price,r.signal_close,rtol=1e-12)
    after=ticks[ticks.transact_time.ge(r.decision_ts+5000)]
    entry=after.iloc[0];assert int(entry.transact_time)==r.entry_exec_ts and np.isclose(entry.price,r.raw_entry_5s,rtol=1e-12)
    suffix=after[after.transact_time.lt(r.ts+60_000)]
    assert len(suffix)==r.suffix_trade_count
    assert np.isclose(suffix.price.max(),r.suffix_high,rtol=1e-12)
    assert np.isclose(suffix.price.min(),r.suffix_low,rtol=1e-12)
    assert np.isclose(suffix.price.iloc[-1],r.suffix_close,rtol=1e-12)
    checked.append({'observation_id':r.observation_id,'contract':r.contract,'day':r.day,'side':int(r.side)})
    print('TOUCH_SAMPLE_OK',r.contract,r.day,flush=True)
report={'sampled_events':len(checked),'checked':checked,
        'limits':'Sample independently rereads the same public trade archive; does not establish market-order fills or intraminute mark-price paths.'}
(HERE/'首次触价逐笔独立抽查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TOUCH_ARCHIVE_SAMPLE_PASS',len(checked),flush=True)
