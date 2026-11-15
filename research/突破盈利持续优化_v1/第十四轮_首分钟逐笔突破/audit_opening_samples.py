"""Independently reread four public tapes and reconstruct first touch and entry."""
import hashlib,io,json
from pathlib import Path
import numpy as np
import pandas as pd
import requests
HERE=Path(__file__).resolve().parent
d=pd.read_parquet(HERE/'首分钟首次触价与五秒参考.parquet')
d=d[d.status.eq('verified')].sort_values(['source_year','contract','trigger_minute']).reset_index(drop=True)
sample=d.iloc[np.unique(np.linspace(0,len(d)-1,min(4,len(d)),dtype=int))];checked=[]
for r in sample.itertuples(index=False):
    name=f'{r.contract}-aggTrades-{r.day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{r.contract}/{name}'
    response=requests.get(url,timeout=(12,120));response.raise_for_status();body=response.content
    assert hashlib.sha256(body).hexdigest()==r.archive_sha256
    chunks=[]
    for c in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=200_000):
        part=c[c.transact_time.ge(r.trigger_minute)&c.transact_time.lt(min(r.trigger_minute+120_000,r.quarter_end))]
        if len(part):chunks.append(part)
    ticks=pd.concat(chunks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
    first_minute=ticks[ticks.transact_time.lt(r.trigger_minute+60_000)]
    cross=first_minute[(first_minute.price>r.upper)|(first_minute.price<r.lower)].iloc[0]
    side=1 if cross.price>r.upper else -1
    assert int(cross.transact_time)==r.decision_ts and side==r.side and np.isclose(cross.price,r.signal_close,rtol=1e-12)
    after=ticks[ticks.transact_time.ge(r.decision_ts+5000)];entry=after.iloc[0]
    assert int(entry.transact_time)==r.entry_exec_ts and np.isclose(entry.price,r.raw_entry_5s,rtol=1e-12)
    suffix=after[after.transact_time.lt(r.ts+60_000)]
    assert len(suffix)==r.suffix_trade_count
    assert np.isclose(suffix.price.max(),r.suffix_high,rtol=1e-12)
    assert np.isclose(suffix.price.min(),r.suffix_low,rtol=1e-12)
    assert np.isclose(suffix.price.iloc[-1],r.suffix_close,rtol=1e-12)
    checked.append({'observation_id':r.observation_id,'contract':r.contract,'day':r.day})
    print('OPENING_SAMPLE_OK',r.contract,r.day,flush=True)
report={'sampled_events':len(checked),'checked':checked,
        'limit':'Sample rereads public archive; does not establish actual order fills or intraminute mark paths.'}
(HERE/'首分钟逐笔独立抽查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('OPENING_SAMPLE_PASS',len(checked),flush=True)
