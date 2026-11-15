"""Independently cross-check official API funding with the prior official monthly archive."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent/'work'
OLD=ROOT/'breakout_forward_2026'/'normalized'
RAW=ROOT/'breakout_november_2026'/'raw'/'fundingRate'
pool=json.loads((HERE.parent/'突破胜率与净收益前瞻检验_v1'/'冻结研究方案.json').read_text(encoding='utf-8'))['fixed_pool']
lo=int(pd.Timestamp('2026-10-28',tz='UTC').timestamp()*1000)
hi=int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000)
checks=[]
for item in pool:
    c=item['contract']; old=pd.read_parquet(OLD/f'{c}_fundingRate.parquet')
    old=old[(old.ts>=lo)&(old.ts<hi)][['ts','last_funding_rate']]
    fresh=pd.DataFrame(json.loads((RAW/f'{c}.json').read_text(encoding='utf-8')))
    fresh=fresh.rename(columns={'fundingTime':'ts','fundingRate':'rate'})
    fresh.ts=pd.to_numeric(fresh.ts).astype('int64');fresh.rate=pd.to_numeric(fresh.rate)
    fresh=fresh[(fresh.ts>=lo)&(fresh.ts<hi)][['ts','rate']]
    merged=old.merge(fresh,on='ts',how='outer',validate='one_to_one',indicator=True)
    if not len(merged) or not merged._merge.eq('both').all():raise ValueError('Funding archive/API coverage mismatch: '+c)
    err=float((merged.last_funding_rate-merged.rate).abs().max())
    if err>1e-12:raise ValueError('Funding archive/API rate mismatch: '+c)
    checks.append({'contract':c,'overlap_rows':len(merged),'max_abs_error':err})
report={'contracts':len(checks),'matched_rate_records':sum(x['overlap_rows'] for x in checks),
        'max_absolute_rate_error':max(x['max_abs_error'] for x in checks),'checks':checks,
        'limitation':'Agreement checks the October overlap; November funding remains the official public API record.'}
(HERE/'新期间资金费交叉核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('NOV_FUNDING_AUDIT_PASS',len(checks),report['matched_rate_records'],report['max_absolute_rate_error'],flush=True)
