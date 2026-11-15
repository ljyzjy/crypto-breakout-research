"""Post-hoc, optimistic remaining-quarter price-space diagnostic (not strategy P&L)."""
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PREV=HERE.parent/'突破柱融合研究_v1'
P2=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase2')
spec=importlib.util.spec_from_file_location('excursion_phase2',P2/'data_io.py')
pio=importlib.util.module_from_spec(spec);spec.loader.exec_module(pio)
M=60_000; Q=15*M

d=pd.read_parquet(HERE/'全部机会与标签.parquet')
s=pd.read_parquet(PREV/'signals.parquet')
d=d[d.label_status.eq('valid')].merge(s[['observation_id','contract','side','quarter_start']],
    on='observation_id',validate='one_to_one')
rows=[]
for contract,g in d.groupby('contract'):
    start=int(g.entry_ts.min()); end=int((g.quarter_start+Q).max())
    raw=pio.load_minutes(contract,start,end).set_index('ts')
    if not raw.index.is_unique:raise ValueError('Duplicate minute')
    for r in g.itertuples(index=False):
        start=int(r.entry_ts); end=int(r.quarter_start)+Q
        ix=np.arange(start,end,M,dtype='int64')
        if not len(ix):raise ValueError('Entry outside quarter')
        p=raw.reindex(ix)
        a=p[['open','high','low','close']].to_numpy(float)
        valid=np.isfinite(a).all() and (a>0).all()
        valid=valid and (a[:,1]>=np.max(a[:,[0,2,3]],axis=1)).all() and (a[:,2]<=np.min(a[:,[0,1,3]],axis=1)).all()
        if not valid:
            rows.append({'observation_id':r.observation_id,'status':'missing_price'});continue
        raw_entry=float(a[0,0]);favorable=float(a[:,1].max() if r.side==1 else a[:,2].min())
        mfe=10000*r.side*(favorable-raw_entry)/raw_entry
        rows.append({'observation_id':r.observation_id,'status':'valid','remaining_minutes':len(ix),
                     'optimistic_favorable_bp':mfe,'reaches_20bp':bool(mfe>=20),
                     'exited_by_quarter_end':bool(r.exit_ts<=end),'full_trade_net_win':bool(r.net_per_notional>0)})
x=pd.DataFrame(rows); assert len(x)==len(d) and x.observation_id.is_unique
j=d.merge(x,on='observation_id',validate='one_to_one')
known=j[j.status.eq('valid')]
out=[]
for (split,group),g in known.groupby(['split','activity_group']):
    out.append({'split':split,'activity_group':group,'count':len(g),
      'median_remaining_minutes':float(g.remaining_minutes.median()),
      'median_optimistic_favorable_bp':float(g.optimistic_favorable_bp.median()),
      'count_reached_20bp':int(g.reaches_20bp.sum()),'pct_reached_20bp':float(100*g.reaches_20bp.mean()),
      'count_exited_by_quarter_end':int(g.exited_by_quarter_end.sum()),
      'net_positive_full_trade_count':int(g.full_trade_net_win.sum())})
pd.DataFrame(out).to_csv(HERE/'柱内潜在空间_描述.csv',index=False,encoding='utf-8-sig')
summary={'total_valid_opportunities':len(d),'future_price_missing':int(j.status.ne('valid').sum()),
 'threshold_bp':20,'interpretation':'Best high/low reached after entry within remaining quarter; ignores whether stop occurred first, order-book liquidity, queue, adverse executions and funding; not realized or realizable profit.',
 'rows':out}
(HERE/'柱内潜在空间_说明.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
