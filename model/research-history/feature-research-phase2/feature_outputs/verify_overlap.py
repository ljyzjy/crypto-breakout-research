"""Verify old/new features on exactly identical historical observation keys."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
OLD=ROOT.parent/'crypto-spot-kit/short-term-research/pullback-research-v2/universe-hours.parquet'
old=pd.read_parquet(OLD,columns=['ts','symbol','return6','residual_score','rvol','count_rvol'])
new=pd.read_parquet(HERE/'matched_legacy_hours.parquet')
joined=old.merge(new[['ts','symbol','new_r6','new_residual6','new_quote_rvol','new_count_rvol']],on=['ts','symbol'],how='outer',validate='one_to_one',indicator=True)
assert len(joined)==len(old) and joined['_merge'].eq('both').all()
checks=[]
for a,b in [('return6','new_r6'),('residual_score','new_residual6'),('rvol','new_quote_rvol'),('count_rvol','new_count_rvol')]:
    mask=np.isfinite(joined[a])&np.isfinite(joined[b])
    av=joined.loc[mask,a].to_numpy();bv=joined.loc[mask,b].to_numpy()
    delta=np.abs(av-bv);ok=np.isclose(av,bv,atol=1e-10,rtol=1e-9)
    bad=joined.loc[mask].loc[~ok,['ts','symbol',a,b]].head(20).to_dict('records')
    checks.append({'old_column':a,'new_column':b,'common_finite_rows':int(mask.sum()),
                   'allclose':bool(ok.all()),'failed_rows':int((~ok).sum()),
                   'max_abs_difference':float(delta.max()) if len(delta) else None,
                   'p99_abs_difference':float(np.quantile(delta,.99)) if len(delta) else None,
                   'examples':bad})
result={'utc':datetime.now(timezone.utc).isoformat(),'same_keys':True,'rows':len(joined),
        'atol':1e-10,'rtol':1e-9,'all_passed':all(x['allclose'] for x in checks),'checks':checks,
        'outcomes_read':False,'old_sha256':hashlib.sha256(OLD.read_bytes()).hexdigest(),
        'new_sha256':hashlib.sha256((HERE/'matched_legacy_hours.parquet').read_bytes()).hexdigest()}
(HERE/'overlap_numeric_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
