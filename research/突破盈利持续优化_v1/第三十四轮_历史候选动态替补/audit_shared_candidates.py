"""Check common candidates' causal inputs and rank/side gates before tape reuse."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
def main():
    source=PARENT/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet'
    target=HERE/'替补动态池潜在触价_待逐笔验证.parquet'
    a=pd.read_parquet(source).set_index('observation_id');b=pd.read_parquet(target).set_index('observation_id')
    assert a.index.is_unique and b.index.is_unique and set(a.index)<=set(b.index)
    direction_checks=0
    for obs,x in a.iterrows():
        y=b.loc[obs]
        for k in ('trigger_minute','quarter_start','quarter_end','symbol','contract','cohort','source_year'):
            assert x[k]==y[k],(obs,k)
        for k in ('upper','lower','atr','prior_prefix_ratio','prior_body_atr'):
            assert np.isclose(float(x[k]),float(y[k]),rtol=1e-10,atol=1e-10),(obs,k)
        for name in ('long','short'):
            assert bool(x[name+'_known_eligible'])==bool(y[name+'_known_eligible'])
            if x[name+'_known_eligible']:
                s=json.loads(x[name+'_spec']);t=json.loads(y[name+'_spec'])
                for k in ('stop_price','level','score','rvol','rank','liquidity_rank'):
                    assert np.isclose(float(s[k]),float(t[k]),rtol=1e-10,atol=1e-10),(obs,name,k)
                direction_checks+=1
    out={'shared_events':len(a),'backup_only_events':len(b)-len(a),'eligible_direction_checks':direction_checks,
         'all_signal_and_rules_match':True,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
         'backup_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
         'note':'Shared tape inputs agree; unresolved source problems remain unresolved in both variants.'}
    (HERE/'共同候选复用独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_SHARED_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
