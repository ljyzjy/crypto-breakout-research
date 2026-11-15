"""Check overlap and account for added unit opportunities without causal claims."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;B=H.parent/'第四十轮_BTC_ETH事前活跃度'
def main():
    before=json.loads((B/'双币活跃度训练诊断.json').read_text(encoding='utf-8'))
    after=json.loads((H/'双币活跃度训练诊断.json').read_text(encoding='utf-8'))
    a=pd.read_parquet(B/'冻结输入'/'baseline_ledger.parquet');b=pd.read_parquet(H/'冻结输入'/'baseline_ledger.parquet')
    am=pd.read_parquet(B/'候选事前市场过滤.parquet').set_index('observation_id')
    bm=pd.read_parquet(H/'候选事前市场过滤.parquet').set_index('observation_id')
    same=am.index.intersection(bm.index)
    assert (am.loc[same,'market_status']==bm.loc[same,'market_status']).all()
    assert (am.loc[same,'allowed_side']==bm.loc[same,'allowed_side']).all()
    rows=[]
    for x in before['rows']:
        lev=x['leverage'];y=next(r for r in after['rows'] if r['leverage']==lev)
        old=set(x['verified_observation_ids']);new=set(y['verified_observation_ids']);assert old.issubset(new)
        variant=f'normal_2r_{lev}x';l=a[a.variant.eq(variant)&a.observation_id.isin(old)].set_index('observation_id')
        r=b[b.variant.eq(variant)&b.observation_id.isin(new)].set_index('observation_id');assert len(l)==len(old) and len(r)==len(new)
        for obs in old:
            for col in ('entry_ts','exit_ts','entry_raw','exit_raw','net_per_unit_notional'):
                assert math.isclose(float(l.loc[obs,col]),float(r.loc[obs,col]),rel_tol=1e-11,abs_tol=1e-12),(obs,col)
        added=new-old;vals=[float(r.loc[v,'net_per_unit_notional']) for v in added]
        rows.append({'leverage':lev,'old_verified':len(old),'overlap_checked':len(old),'added_verified':len(added),
                     'added_net_positive':sum(v>0 for v in vals),'added_mean_net_pct_notional':100*sum(vals)/len(vals) if vals else None})
    out={'common_candidate_market_decisions_checked':len(same),'rows':rows,'all_checks_pass':True,
         'note':'Additional opportunities are not independent evidence; market universe and candidate selection differ.'}
    (H/'候选池增量独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL42_INCREMENT_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
