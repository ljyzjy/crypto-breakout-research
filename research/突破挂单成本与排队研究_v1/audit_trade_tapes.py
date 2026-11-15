"""Reconcile extracted aggTrade quote volume against independent 1m kline records."""
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_maker_tapes_2026'
NORM=HERE.parent.parent/'work'/'breakout_forward_2026'/'normalized'
manifest=json.loads((HERE/'逐笔成交数据校验.json').read_text(encoding='utf-8'))
lookup={(r['contract'],r['day']):r for r in manifest['records']}
signals=pd.read_parquet(HERE/'计划下单候选.parquet')
M=60_000;DAY=86_400_000;END=1793491200000

@lru_cache(maxsize=64)
def ticks(c,day):
    p=WORK/'tapes'/f'{c}_{day}.parquet'
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()
@lru_cache(maxsize=18)
def klines(c):return pd.read_parquet(NORM/f'{c}_klines.parquet').set_index('ts')['quote_volume']

tests=[]
for s in signals.itertuples(index=False):
    start=int(s.ts);end=min(start+63*M,END)
    if end<=start:continue
    frames=[];day=start//DAY*DAY;missing=False
    while day<end:
        tag=pd.Timestamp(day,unit='ms',tz='UTC').strftime('%Y-%m-%d')
        if lookup.get((s.contract,tag),{}).get('status')!='verified':missing=True;break
        frames.append(ticks(s.contract,tag));day+=DAY
    if missing:tests.append({'observation_id':s.observation_id,'status':'archive_unknown'});continue
    tape=pd.concat(frames,ignore_index=True)
    tape=tape[(tape.transact_time>=start)&(tape.transact_time<end)].copy()
    tape['minute']=tape.transact_time//M*M
    tape['quote']=tape.price*tape.quantity
    got=tape.groupby('minute').quote.sum()
    ix=np.arange(start,end,M,dtype=np.int64)
    expected=klines(s.contract).reindex(ix).to_numpy(float)
    actual=got.reindex(ix,fill_value=0).to_numpy(float)
    valid=np.isfinite(expected)&(expected>0)
    rel=np.abs(actual[valid]-expected[valid])/expected[valid]
    expiry=min(start+3*M,int(s.quarter_start)+15*M)
    entry=(ix<expiry)&valid
    entry_rel=np.abs(actual[entry]-expected[entry])/expected[entry]
    tests.append({'observation_id':s.observation_id,'status':'compared','minutes':int(valid.sum()),
                  'bad_minutes_gt_1pct':int((rel>.01).sum()),'max_relative_error':float(rel.max()) if len(rel) else None,
                  'median_relative_error':float(np.median(rel)) if len(rel) else None,
                  'entry_minutes':int(entry.sum()),'entry_bad_minutes_gt_1pct':int((entry_rel>.01).sum()),
                  'max_entry_relative_error':float(entry_rel.max()) if len(entry_rel) else None})
out=pd.DataFrame(tests);out.to_csv(HERE/'逐笔对分钟成交额核验.csv',index=False,encoding='utf-8-sig')
ok=out[out.status.eq('compared')]
report={'opportunities_compared':len(ok),'archive_unknown':int(out.status.eq('archive_unknown').sum()),
        'minutes_compared':int(ok.minutes.sum()),'minutes_gt_1pct_difference':int(ok.bad_minutes_gt_1pct.sum()),
        'opportunities_with_any_minute_gt_1pct':int((ok.bad_minutes_gt_1pct>0).sum()),
        'entry_window_minutes_compared':int(ok.entry_minutes.sum()),
        'entry_window_minutes_gt_1pct_difference':int(ok.entry_bad_minutes_gt_1pct.sum()),
        'opportunities_with_entry_mismatch_gt_1pct':int((ok.entry_bad_minutes_gt_1pct>0).sum()),
        'interpretation':'Checks aggregate traded notional against 1m klines, not order-book state, priority, or executable fills.'}
(HERE/'逐笔数据覆盖核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TAPE_AUDIT',json.dumps(report,ensure_ascii=False),flush=True)
