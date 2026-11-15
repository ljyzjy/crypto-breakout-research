"""Describe candidate-cohort large-bar captures after close, with unknowns."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def main():
    assert json.loads((H/'2023大柱行情样本核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    q=json.loads((H/'事后标签质量.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'2023候选事后大柱标签.parquet').read_bytes()).hexdigest()==q['label_sha256']
    cand=pd.read_parquet(I/'candidates.parquet').set_index('observation_id')
    sig=pd.read_parquet(I/'signals.parquet').set_index('observation_id')
    lab=pd.read_parquet(H/'2023候选事后大柱标签.parquet').set_index('observation_id')
    ledger=pd.read_parquet(I/'ledger.parquet')
    assert cand.index.is_unique and sig.index.is_unique and lab.index.is_unique and set(cand.index)==set(sig.index)==set(lab.index)
    large={i for i,r in lab.iterrows() if r.status=='verified' and bool(r.large)}
    rows=[]
    for lev in (10,20):
        paths=ledger[ledger.variant.eq(f'normal_2r_{lev}x')];assert paths.observation_id.is_unique
        byid={r['observation_id']:r for r in paths.to_dict('records')};good={};unknown=set()
        for obs,e in sig.iterrows():
            if e.status not in BENIGN:unknown.add(obs);continue
            if e.status!='qualified':continue
            pre=e[f'precheck_{lev}x']
            if pd.isna(pre):unknown.add(obs);continue
            if pre!='passed':continue
            r=byid.get(obs)
            if r is None or r['status']!='verified' or r['risk_status']!='verified' or r['liq_proxy']:unknown.add(obs);continue
            assert int(r['entry_ts'])>=int(r['decision_ts'])+10_000
            good[obs]=r
        matched={i:r for i,r in good.items() if i in large and int(r['side'])==int(lab.loc[i,'allowed_side']) and int(r['entry_ts'])<int(cand.loc[i,'quarter_end'])}
        possible=large&unknown;assert not possible&set(matched)
        vals=[float(r['net_pct_notional']) for r in matched.values()]
        other=[float(r['net_pct_notional']) for i,r in good.items() if i not in matched]
        rows.append({'leverage':lev,'known_large_candidates':len(large),'verified_entries':len(good),
                     'verified_large_direction_entries':len(matched),'large_entry_net_wins':sum(x>0 for x in vals),
                     'large_entry_mean_net_pct_notional':float(np.mean(vals)) if vals else None,
                     'other_entries':len(other),'other_entry_net_wins':sum(x>0 for x in other),
                     'other_entry_mean_net_pct_notional':float(np.mean(other)) if other else None,
                     'unknown_large_candidates':len(possible),'known_large_not_captured':len(large)-len(possible)-len(matched),
                     'observed_large_candidate_capture_pct':100*len(matched)/len(large) if large else None,
                     'optimistic_large_candidate_capture_pct':100*(len(matched)+len(possible))/len(large) if large else None,
                     'matched_observation_ids':sorted(matched),'unknown_large_observation_ids':sorted(possible)})
    out={'candidate_events':len(cand),'post_close_label_verified':int(lab.status.eq('verified').sum()),
         'post_close_label_unknown':int(lab.status.ne('verified').sum()),'known_large_candidates':len(large),
         'rows':rows,'note':'Post-close candidate-cohort description, not a live entry rule, market-wide recall or account return.'}
    (H/'2023大柱捕捉事后诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE45_DIAGNOSIS',json.dumps({**out,'rows':[{k:v for k,v in r.items() if not k.endswith('_ids')} for r in rows]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
