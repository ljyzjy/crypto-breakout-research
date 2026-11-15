"""Reconcile all unit returns and independently reread selected tick paths."""
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
rows=pd.read_parquet(HERE/'秒级退出逐机会_2026训练.parquet')
meta=json.loads((HERE/'秒级退出探索结果.json').read_text(encoding='utf-8'))
d=rows[rows.status.eq('verified')].copy();assert len(d)==43
for r in d.itertuples(index=False):
    assert r.entry_ts>=r.decision_ts+5000
    side=int(r.side);entry=float(r.entry_fill);qty=1/entry
    assert np.isclose(entry,r.entry_raw*(1+side*.0005),rtol=1e-12)
    for h in (15,30,60):
        signal=int(getattr(r,f'h{h}_exit_signal_ts'));exit_ts=int(getattr(r,f'h{h}_exit_ts'))
        raw=float(getattr(r,f'h{h}_exit_raw'));reason=getattr(r,f'h{h}_exit_reason')
        assert r.entry_ts<=signal<=r.entry_ts+h*1000 and exit_ts>=signal+5000
        if reason=='time':assert signal==r.entry_ts+h*1000
        exit_fill=raw*(1-side*.0005);funding=float(getattr(r,f'h{h}_funding_per_notional'))
        net=side*qty*(exit_fill-entry)-.0005-qty*exit_fill*.0005-funding
        assert np.isclose(net,getattr(r,f'h{h}_net_per_notional'),rtol=1e-11,atol=1e-12)
for item in meta['strategies']:
    h=item['holding_seconds'];values=d[f'h{h}_net_per_notional'].to_numpy(float)
    assert len(values)==item['trades'] and np.isclose(values.sum(),item['sum_net_per_unit_notional'])
    assert np.isclose(100*(values>0).mean(),item['net_win_rate_pct'])

sample=d.sort_values(['contract','trigger_minute']).iloc[np.unique(np.linspace(0,len(d)-1,min(4,len(d)),dtype=int))]
checked=[]
for r in sample.itertuples(index=False):
    name=f'{r.contract}-aggTrades-{r.day}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{r.contract}/{name}'
    response=requests.get(url,timeout=(12,120));response.raise_for_status();body=response.content
    assert hashlib.sha256(body).hexdigest()==r.archive_sha256
    pieces=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=200_000):
        part=chunk[chunk.transact_time.ge(r.trigger_minute)&chunk.transact_time.lt(r.trigger_minute+180_000)]
        if len(part):pieces.append(part)
    ticks=pd.concat(pieces,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort').reset_index(drop=True)
    first=ticks[ticks.transact_time.lt(r.trigger_minute+60_000)]
    hit=first[(first.price>r.upper)|(first.price<r.lower)].iloc[0]
    assert int(hit.transact_time)==r.decision_ts
    entry_idx=int(ticks.index[ticks.transact_time.ge(r.decision_ts+5000)][0]);entry=ticks.iloc[entry_idx]
    assert int(entry.transact_time)==r.entry_ts and np.isclose(entry.price,r.entry_raw,rtol=1e-12)
    later=ticks.iloc[entry_idx+1:];side=int(r.side)
    for h in (15,30,60):
        deadline=r.entry_ts+h*1000;before=later[later.transact_time.le(deadline)]
        hits=before[((before.price<=r.stop_price) if side==1 else (before.price>=r.stop_price)) |
                    ((before.price>=r.target) if side==1 else (before.price<=r.target))]
        trigger=int(hits.iloc[0].transact_time) if len(hits) else deadline
        exitrow=later[later.transact_time.ge(trigger+5000)].iloc[0]
        assert trigger==getattr(r,f'h{h}_exit_signal_ts')
        assert int(exitrow.transact_time)==getattr(r,f'h{h}_exit_ts')
        assert np.isclose(exitrow.price,getattr(r,f'h{h}_exit_raw'),rtol=1e-12)
    checked.append({'contract':r.contract,'day':r.day,'observation_id':r.observation_id})
    print('SECOND_EXIT_SAMPLE_OK',r.contract,r.day,flush=True)
report={'unit_trades_checked':len(d),'exit_paths_reconciled':len(d)*3,'original_archives_sampled':len(checked),
        'sample':checked,'limits':'Same public data; unit-notional paths are not a shared-account simulation or confirmed market-order fills.'}
(HERE/'秒级退出独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('SECOND_EXIT_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
