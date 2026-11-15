"""Audit normalized extra contracts, recorded gaps and preserved original files."""
import hashlib,json,os,shutil
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
NORM=ROOT/'work'/'breakout_2024_expanded18'/'normalized';OLD=ROOT/'work'/'breakout_2024_11'/'normalized'
meta=json.loads((HERE/'新增七币2024档案校验.json').read_text(encoding='utf-8'))
assert not meta['errors'] and len(meta['records'])==7*(7+6+6)
assert meta['verified_records']+len(meta['missing_404'])==len(meta['records'])
checks=[]
for c in meta['contracts']:
  for kind in ('klines','markPriceKlines','fundingRate'):
    f=NORM/f'{c}_{kind}.parquet';d=pd.read_parquet(f)
    rows=[x for x in meta['records'] if x['contract']==c and x['kind']==kind and x['status']=='verified']
    assert len(d)==sum(x['rows'] for x in rows) and not d.ts.duplicated().any() and d.ts.is_monotonic_increasing
    if kind=='fundingRate':
        assert np.isfinite(d[['funding_interval_hours','last_funding_rate']].to_numpy(float)).all()
        assert (d.funding_interval_hours>0).all()
    elif len(d):
        prices=d[['open','high','low','close']].to_numpy(float)
        assert np.isfinite(prices).all() and (prices>0).all() and (d.ts%60_000==0).all()
        assert (prices[:,1]>=prices[:,[0,2,3]].max(axis=1)).all()
        assert (prices[:,2]<=prices[:,[0,1,3]].min(axis=1)).all()
    checks.append({'contract':c,'kind':kind,'rows':len(d),'verified_months':len(rows),
                   'first_ts':int(d.ts.min()) if len(d) else None,'last_ts':int(d.ts.max()) if len(d) else None})
for x in meta['reused_existing_files']:
    source=OLD/x['file'];dest=NORM/x['file']
    assert source.is_file() and dest.is_file() and source.stat().st_size==dest.stat().st_size
    if not os.path.samefile(source,dest):assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(dest.read_bytes()).digest()
assert shutil.disk_usage(NORM).free>=meta['disk_reserve_bytes']
out={'extra_normalized_files_checked':len(checks),'original_files_checked':len(meta['reused_existing_files']),
     'verified_monthly_archives':meta['verified_records'],'missing_monthly_archives':len(meta['missing_404']),
     'disk_free_bytes':shutil.disk_usage(NORM).free,'details':checks,
     'note':'Missing archive coverage remains missing; a 404 alone is not interpreted as proof of listing status.'}
(HERE/'十八币历史数据质量复核.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXPANDED18_DATA_AUDIT_PASS',json.dumps({k:out[k] for k in ['extra_normalized_files_checked','original_files_checked','verified_monthly_archives','missing_monthly_archives','disk_free_bytes']}),flush=True)
