"""Describe the fixed P5 buffer on previously verified unit paths."""
import hashlib,json
from collections import Counter
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
def main():
    audit=json.loads((H/'缓冲时序独立核验.json').read_text(encoding='utf-8'));assert audit['all_checks_pass']
    meta=json.loads((H/'缓冲事前决定质量.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'P5缓冲事前决定.parquet').read_bytes()).hexdigest()==meta['decision_sha256']
    prior=json.loads((I/'dual_result.json').read_text(encoding='utf-8'));score=pd.read_parquet(H/'P5缓冲事前决定.parquet')
    ledger=pd.read_parquet(I/'ledger.parquet');result=[]
    for lev in (10,20):
        p=next(x for x in prior['rows'] if x['leverage']==lev);q=score[score.leverage.eq(lev)]
        selected=set(q.loc[q.decision.eq('selected_known_inputs'),'observation_id']);old=set(p['verified_observation_ids'])
        assert selected.issubset(old)
        unknown=set(q.loc[q.decision.isin(['source_unknown','market_unknown','precheck_unknown','feature_unknown']),'observation_id'])
        assert set(p['unknown_observation_ids']).issubset(unknown)
        g=ledger[ledger.variant.eq(f'normal_2r_{lev}x')&ledger.observation_id.isin(selected)]
        assert len(g)==len(selected) and g.risk_status.eq('verified').all() and not g.liq_proxy.any()
        prior_g=ledger[ledger.variant.eq(f'normal_2r_{lev}x')&ledger.observation_id.isin(old)]
        assert len(prior_g)==len(old)
        x=g.net_per_unit_notional.to_numpy(float);n=len(x);w=int((x>0).sum());u=len(unknown)
        pos=float(x[x>0].sum());neg=float(-x[x<0].sum())
        result.append({'leverage':lev,'prior_verified_events':p['verified_events'],'prior_unsafe_fills':int(prior_g.reason.eq('filled_beyond_risk_budget').sum()),
          'buffer_verified_events':n,'buffer_net_wins':w,'buffer_win_rate_pct':100*w/n if n else None,
          'buffer_mean_net_pct_notional':float(100*x.mean()) if n else None,'profit_factor':pos/neg if neg else None,
          'remaining_unknown_events':u,'optimistic_unit_win_rate_upper_pct':100*(w+u)/(n+u) if n+u else None,
          'buffer_unsafe_fills':int(g.reason.eq('filled_beyond_risk_budget').sum()),'exit_reasons':dict(Counter(g.reason)),
          'passes_predeclared_minimum_sample':n>=50,'selected_observation_ids':sorted(selected)})
    out={'period':'2024_jan_apr','rows':result,'note':'Post hoc risk-motivated exploratory subset, not an account or prospective result.'}
    (H/'事前缓冲训练诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BUFFER41_DIAGNOSIS',json.dumps({**out,'rows':[{k:v for k,v in z.items() if k!='selected_observation_ids'} for z in result]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
