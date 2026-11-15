"""Post-hoc concentration diagnostics and independent feature spot-checks."""
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PREV=HERE.parent/'突破柱融合研究_v1'
P2=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase2')
spec=importlib.util.spec_from_file_location('sensitivity_p2',P2/'data_io.py')
pio=importlib.util.module_from_spec(spec);spec.loader.exec_module(pio)
M=60_000

d=pd.read_parquet(HERE/'全部机会与标签.parquet')
s=pd.read_parquet(PREV/'signals.parquet')
joined=d.merge(s[['observation_id','symbol','contract','side','break_ts','signal_close','level','atr','quarter_start']],
               on='observation_id',validate='one_to_one')
assert len(joined)==1822
samples=pd.concat([joined.head(5),joined.tail(5),joined[joined.activity_group.eq('active_sync')].iloc[::7].head(15)]).drop_duplicates('observation_id')
for r in samples.itertuples(index=False):
    raw=pio.load_minutes(r.contract,int(r.break_ts),int(r.break_ts)+M)
    assert len(raw)==1 and int(raw.ts.iloc[0])==int(r.break_ts)
    bar=raw.iloc[0]; width=float(bar.high-bar.low)
    body=float(r.side*(bar.close-bar.open)/width) if width>0 else np.nan
    extension=float(r.side*(r.signal_close-r.level)/r.atr)
    assert np.isclose(body,r.body_fraction,equal_nan=True)
    assert np.isclose(extension,r.extension_atr)
    assert int((r.decision_ts-r.quarter_start)//M)==r.elapsed_minute
    assert r.feature_max_known_ts==r.decision_ts

target=joined[(joined.split=='later')&(joined.label_status=='valid')&(joined.activity_group=='active_sync')].copy()
target['net_bp']=target.net_per_notional*10000
target=target.sort_values('net_bp',ascending=False)
byday=target.groupby('day').net_bp.agg(['size','sum']).sort_values('sum',ascending=False)
bysymbol=target.groupby('symbol').net_bp.agg(['size','sum']).sort_values('sum',ascending=False)
target['month']=target.day.str[:7]
monthly=target.groupby('month').net_bp.agg(['size','mean','sum'])
report={'scope':'Post-hoc sensitivity, not an investable removal rule.',
 'feature_spot_checks':len(samples), 'later_active_sync_n':len(target),
 'net_bp_mean':float(target.net_bp.mean()), 'total_net_bp':float(target.net_bp.sum()),
 'best_one_net_bp':float(target.net_bp.iloc[0]),
 'mean_without_best_one_bp':float(target.net_bp.iloc[1:].mean()),
 'best_three_net_bp':float(target.net_bp.iloc[:3].sum()),
 'mean_without_best_three_bp':float(target.net_bp.iloc[3:].mean()),
 'days_with_opportunities':len(byday), 'symbols_with_opportunities':len(bysymbol),
 'best_day_contribution_bp':float(byday['sum'].iloc[0]),
 'exit_reason_counts':target.reason.value_counts().to_dict(),
 'month_results':monthly.reset_index().to_dict('records')}
(HERE/'集中度敏感性.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
byday.to_csv(HERE/'后段同步组_逐日.csv',encoding='utf-8-sig')
bysymbol.to_csv(HERE/'后段同步组_逐币.csv',encoding='utf-8-sig')
print(json.dumps(report,ensure_ascii=False,indent=2))
