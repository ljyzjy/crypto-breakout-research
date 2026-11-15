"""Re-read newly downloaded 18-pool event tapes and reconstruct 5s features."""
import hashlib,io,json,time
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent
d=pd.read_parquet(HERE/'十八币首次触价五秒成交.parquet')
d=d[d.status.eq('verified')&d.tape_source.eq('downloaded')].sort_values(['source_year','contract','trigger_minute']).reset_index(drop=True)
sample=d.iloc[np.unique(np.linspace(0,len(d)-1,min(4,len(d)),dtype=int))];checked=[]
for r in sample.itertuples(index=False):
    name=f'{r.contract}-aggTrades-{r.day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{r.contract}/{name}'
    error=None
    for attempt in range(3):
        try:
            response=requests.get(url,timeout=(20,120));response.raise_for_status();body=response.content;break
        except requests.RequestException as exc:
            error=exc
            if attempt<2:time.sleep(attempt+1)
    else:raise RuntimeError('sample_archive_unavailable:'+r.contract+':'+r.day) from error
    assert hashlib.sha256(body).hexdigest()==r.archive_sha256==r.flow_archive_sha
    pieces=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker'],dtype={'is_buyer_maker':str},chunksize=200_000):
        part=chunk[chunk.transact_time.ge(r.trigger_minute)&chunk.transact_time.lt(min(r.trigger_minute+120_000,r.quarter_end))]
        if len(part):pieces.append(part)
    ticks=pd.concat(pieces,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort').reset_index(drop=True)
    first=ticks[ticks.transact_time.lt(r.trigger_minute+60_000)]
    cross=first[(first.price>r.upper)|(first.price<r.lower)].iloc[0]
    assert int(cross.transact_time)==r.decision_ts and (1 if cross.price>r.upper else -1)==r.side
    assert np.isclose(cross.price,r.signal_close,rtol=1e-12)
    after=ticks[ticks.transact_time.ge(r.decision_ts+5000)];entry=after.iloc[0]
    assert int(entry.transact_time)==r.entry_exec_ts and np.isclose(entry.price,r.raw_entry_5s,rtol=1e-12)
    suffix=after[after.transact_time.lt(r.ts+60_000)]
    assert len(suffix)==r.suffix_trade_count and np.isclose(suffix.price.max(),r.suffix_high,rtol=1e-12)
    assert np.isclose(suffix.price.min(),r.suffix_low,rtol=1e-12) and np.isclose(suffix.price.iloc[-1],r.suffix_close,rtol=1e-12)
    window=ticks[ticks.transact_time.gt(r.decision_ts)&ticks.transact_time.lt(r.decision_ts+5000)]
    assert len(window)==r.five_count
    if len(window):
        vals=window.price.to_numpy(float)*window.quantity.to_numpy(float);maker=window.is_buyer_maker.str.lower()
        buy=float(vals[maker.eq('false').to_numpy()].sum());sell=float(vals[maker.eq('true').to_numpy()].sum())
        assert np.isclose(buy,r.buy_notional,rtol=1e-11) and np.isclose(sell,r.sell_notional,rtol=1e-11)
        assert np.isclose(r.side*(buy-sell)/(buy+sell),r.five_imbalance,rtol=1e-11,atol=1e-12)
    checked.append({'id':r.observation_id,'contract':r.contract,'day':r.day})
    print('EXPANDED18_TAPE_SAMPLE_OK',r.contract,r.day,flush=True)
out={'sampled_archives':len(checked),'samples':checked,'limit':'Rechecks publicly reported trades; does not establish actual order fills.'}
(HERE/'十八币新增逐笔样本复核.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXPANDED18_TAPE_SAMPLE_PASS',len(checked),flush=True)
