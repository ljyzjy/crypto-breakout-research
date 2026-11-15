"""Independently rebuild per-group included IDs from feature outputs, without labels."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];OUT=Path(__file__).resolve().parent
START=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
END=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)
GROUPS={'F1':('clock',['r6','residual6']),'F2':('clock',['efficiency6','concentration6']),'F3':('clock',['rv_relative60','range_atr']),'F4':('events',['boundary_distance','outside_fraction5']),'F5':('events',['drawdown_atr','recovery_fraction']),'F6':('clock',['quote_rvol','count_rvol'])}
summary=json.loads((ROOT/'matched_samples/summary.json').read_text(encoding='utf-8'))
SUMMARY_HASH_AT_START=hashlib.sha256((ROOT/'matched_samples/summary.json').read_bytes()).hexdigest()
for item in summary['groups']:
    candidate=ROOT/'matched_samples'/item['shared_mask']
    assert hashlib.sha256(candidate.read_bytes()).hexdigest()==item['shared_mask_sha256'],'Matched output not ready/changed: '+candidate.name
rows=[]
for group,(cohort,extra) in GROUPS.items():
    expected=set();all_ids=set()
    for p in sorted((ROOT/'feature_outputs'/cohort).glob('*.parquet')):
        d=pd.read_parquet(p)
        if d.empty:continue
        d=d.copy()  # retain pending/out-of-segment source rows in the rejected mask
        ids=d.event_id.astype(str) if cohort=='events' else d.symbol.astype(str)+'|'+d.decision_ts.astype(str)
        all_ids.update(ids)
        shared=np.isfinite(d[['r6','btc_r6','vol24','quote_rvol']].to_numpy(float)).all(axis=1)
        group_valid=np.isfinite(d[extra].to_numpy(float)).all(axis=1)
        m=d.eligible_decision.fillna(False).astype(bool)&~d.quarantined.fillna(False).astype(bool)&d.minute_valid.fillna(False).astype(bool)
        m &= d.contract.notna()&d.contract.ne('')&d.side.notna()&d.side.ne(0)
        m &= shared&group_valid&d.decision_ts.ge(START)&d.decision_ts.lt(END-65*60000)
        if group=='F1':m &= d.symbol.ne('BTCUSDT')
        if cohort=='events':m &= d.event_status.eq('measured')
        expected.update(ids[m])
    mask=pd.read_parquet(ROOT/'matched_samples'/f'{group}-mask.parquet')
    actual=set(mask.loc[mask.included,'observation_id']);actual_all=set(mask.observation_id)
    item=next(x for x in summary['groups'] if x['group']==group)
    h=hashlib.sha256()
    for key in sorted(actual):h.update(key.encode('utf-8')+b'\n')
    digest=h.hexdigest()
    result={'group':group,'reconstructed_included':len(expected),'mask_included':len(actual),'all_records':len(actual_all),'expected_all_records':len(all_ids),'missing_ids':len(expected-actual),'extra_ids':len(actual-expected),'kept_and_rejected_retained':actual_all==all_ids,'independently_recomputed_id_sha256':digest,'baseline_hash_matches':digest==item['baseline_id_sha256'],'enhanced_hash_matches':digest==item['enhanced_id_sha256']}
    result['passed']=expected==actual and actual_all==all_ids and result['baseline_hash_matches'] and result['enhanced_hash_matches']
    rows.append(result)
assert hashlib.sha256((ROOT/'matched_samples/summary.json').read_bytes()).hexdigest()==SUMMARY_HASH_AT_START,'Matched summary changed during audit'
report={'utc':datetime.now(timezone.utc).isoformat(),'all_passed':all(r['passed'] for r in rows),'groups':rows,'scope':'Independent included-ID reconstruction using original per-group eligibility, available controls/variables, direction and measured decision-time65min purge. No outcomes or regressions. Does not certify later label construction.','matched_summary_sha256':SUMMARY_HASH_AT_START,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(OUT/'matched_independent.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
