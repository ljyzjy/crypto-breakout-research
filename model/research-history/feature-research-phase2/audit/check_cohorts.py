"""Independent full-output schema, coverage and temporal-envelope audit."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];OUT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'feature_outputs/manifest.json').read_text(encoding='utf-8'))
source=json.loads((ROOT/'data/manifest.json').read_text(encoding='utf-8'))
pools=json.loads(Path(source['daily_pools_path']).read_text(encoding='utf-8'))
expected_clock=sum(len(d['pool'])*48 for d in pools)
expected_by_symbol={}
for day in pools:
    for item in day['pool']:expected_by_symbol[item['symbol']]=expected_by_symbol.get(item['symbol'],0)+48
features=['r6','residual6','efficiency6','concentration6','rv_relative60','range_atr','boundary_distance','outside_fraction5','drawdown_atr','recovery_fraction','quote_rvol','count_rvol']
results=[];seen={'clock':set(),'event':set()};counts={'clock':0,'event':0};failures=[]
for rec in manifest['records']:
    if rec['kind'] not in counts:continue
    p=Path(rec['path']);d=pd.read_parquet(p);kind=rec['kind'];counts[kind]+=len(d)
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    if digest!=rec['sha256']:failures.append({'file':p.name,'issue':'hash_mismatch'})
    ids=set(d.row_id.astype(str))
    if len(ids)!=len(d) or ids&seen[kind]:failures.append({'file':p.name,'issue':'duplicate_row_id'})
    seen[kind]|=ids
    violations={}
    for col in ('feature_known_ts','hourly_known_ts','minute_known_ts','source_max_known_ts'):
        if col in d:violations[col]=int((pd.to_numeric(d[col],errors='coerce')>d.decision_ts).sum())
    for col in ('efficiency6','concentration6','outside_fraction5','recovery_fraction'):
        if col in d:
            z=pd.to_numeric(d[col],errors='coerce');violations[col+'_range']=int((z.lt(-1e-10)|z.gt(1+1e-10)).sum())
    for col in ('drawdown_atr','range_atr','rv_relative60','quote_rvol','count_rvol'):
        z=pd.to_numeric(d[col],errors='coerce');violations[col+'_negative']=int(z.lt(-1e-10).sum())
    for col in features:violations[col+'_infinite']=int(np.isinf(pd.to_numeric(d[col],errors='coerce')).sum())
    if len(d):violations['invalid_timestamp_unit']=int(d.decision_ts.lt(1_000_000_000_000).sum())
    if kind=='clock':
        violations['clock_symbol_row_count_difference']=abs(len(d)-expected_by_symbol.get(rec['symbol'],0))
        if source['mapping'].get(rec['symbol']) is None:
            violations['unmapped_marked_valid']=int(d.decision_valid.sum())
            violations['unmapped_fabricated_feature']=int(d[features].notna().any(axis=1).sum())
    if kind=='event' and len(d):
        violations['decision_not_t0_plus6m']=int(d.decision_ts.ne(d.t0_open_ts+360000).sum())
        pending=d.event_status.eq('pending_measurement')
        violations['pending_published_event_feature']=int(d.loc[pending,['boundary_distance','outside_fraction5','drawdown_atr','recovery_fraction']].notna().any(axis=1).sum())
        violations['nonmeasured_decision_valid']=int((d.decision_valid&d.event_status.ne('measured')).sum())
        violations['duplicate_event_within60m']=int(d.sort_values('t0_open_ts').t0_open_ts.diff().lt(3600000).sum())
    if any(violations.values()):failures.append({'file':p.name,'issue':'value_or_time_invariant','violations':{k:v for k,v in violations.items() if v}})
    results.append({'kind':kind,'symbol':rec['symbol'],'rows':len(d),'nonnull':{k:int(d[k].notna().sum()) for k in features},'decision_valid':int(d.decision_valid.sum()),'violations':{k:v for k,v in violations.items() if v}})
if counts['clock']!=expected_clock:failures.append({'issue':'clock_opportunity_count','actual':counts['clock'],'expected':expected_clock})
report={'utc':datetime.now(timezone.utc).isoformat(),'scope':'All produced clock/event files: keys, hashes, theoretical known-time envelope, bounded features and declared row retention. Does not verify live receive latency or future profitability.','expected_raw_clock_rows':expected_clock,'expected_clock_by_symbol':expected_by_symbol,'actual_rows':counts,'files_checked':len(results),'failed':failures,'all_passed':not failures,'by_symbol':results,'feature_manifest_sha256':hashlib.sha256((ROOT/'feature_outputs/manifest.json').read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(OUT/'coverage_independent.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({'files_checked':len(results),'rows':counts,'all_passed':not failures,'failures':failures},ensure_ascii=True))
