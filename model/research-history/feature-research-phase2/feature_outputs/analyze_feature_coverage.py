"""Availability and historical-window diagnosis only; no future outcomes."""
from pathlib import Path
from datetime import datetime,timezone
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
keys=pd.read_parquet(HERE/'matched_legacy_hours.parquet')
records=[];allrows=[]
for symbol,g in keys.groupby('symbol',sort=True):
    h=pd.read_parquet(HERE/'hourly'/f'{symbol}.parquet').set_index('ts')
    a=h.reindex(g.ts.to_numpy()).reset_index(drop=True)
    a['symbol']=symbol;a['ts']=g.ts.to_numpy()
    isbtc=g.contract.iloc[0]=='BTCUSDT'
    miss=a.residual6.isna()
    reason=np.select([
       np.full(len(a),isbtc),~miss,
       a.regression_pairs.isna(),a.regression_pairs.lt(720),
       a.alpha.isna()|a.beta.isna(),a.r6.isna()|a.btc_r6.isna(),
       a.residual_variance24.isna(),a.residual_variance24.le(1e-20)],
       ['btc_self_structural','available','short_calendar_fit_history','incomplete_valid_720_pair_window',
        'fit_numerically_unavailable','incomplete_recent_6h','incomplete_recent_24h','residual_variance_too_small'],
       default='other_unavailable')
    a['residual_missing_reason']=reason
    available=int((~miss).sum())
    row={'symbol':symbol,'contract':g.contract.iloc[0],'eligible_hours':len(a),
         'old_residual_available':int(g.residual_score.notna().sum()),
         'new_residual_available':available,'new_residual_fraction':None if isbtc else available/len(a),
         'reasons':{str(k):int(v) for k,v in a.residual_missing_reason.value_counts().items()},
         'quote_rvol_available':int(a.quote_rvol.notna().sum()),'count_rvol_available':int(a.count_rvol.notna().sum())}
    records.append(row);allrows.append(a[['ts','symbol','regression_pairs','residual_missing_reason']])
out=pd.concat(allrows,ignore_index=True)
out.to_parquet(HERE/'residual_availability_reasons.parquet',index=False)
summary={'utc':datetime.now(timezone.utc).isoformat(),'rows':len(out),
         'reason_counts':{str(k):int(v) for k,v in out.residual_missing_reason.value_counts().items()},
         'by_symbol':records,
         'interpretation':'This decomposes mathematical availability constraints. incomplete_valid_720_pair_window is not proof of missing archive: zero-volume/invalid hours also break strict contiguous pairs. Data audit separately verifies requested raw minute coverage. Rules unchanged; no missing values filled.',
         'outcomes_read':False}
(HERE/'residual_availability_reasons.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'reason_counts':summary['reason_counts'],'previous_zero_coverage_symbols':[r for r in records if r['old_residual_available']==0 and r['contract']!='BTCUSDT']},ensure_ascii=True))
