"""Select only causal P10 pullback candidates; never consult old exits or PnL."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
import numpy as np,pandas as pd

HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ORIG=PARENT/'第三十三轮_动态池逐笔执行'
sys.path.insert(0,str(ORIG))
from leveraged_paths import known_precheck

def main():
    s=pd.read_parquet(ORIG/'动态池逐笔信号筛查.parquet')
    p=pd.read_parquet(ORIG/'动态池延迟市价路径.parquet')
    meta=json.loads((ORIG/'动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    assert s.observation_id.is_unique and not p.duplicated(['observation_id','variant']).any()
    base=s[s.status.eq('qualified')].set_index('observation_id');out={};counts=Counter();unknown=set()
    for L in (10,20):
        # An old exit, exit status, return and account outcome cannot affect this decision.
        q=p[p.variant.eq(f'normal_2r_{L}x')][['observation_id','entry_ts','entry_raw']]
        for r in q.itertuples(index=False):
            if pd.isna(r.entry_ts) or pd.isna(r.entry_raw):unknown.add(r.observation_id);continue
            e=base.loc[r.observation_id].to_dict();e['observation_id']=r.observation_id
            t=int(r.entry_ts);v=float(r.entry_raw);side=int(e['side'])
            assert t>=int(e['entry_exec_ts'])+5000 and t<int(e['quarter_end'])
            if side*(v-float(e['raw_entry_5s']))>=0:counts[f'{L}x_no_pullback']+=1;continue
            if side*(v-float(e['level']))<=0:counts[f'{L}x_not_outside_level']+=1;continue
            reason=known_precheck({**e,'entry_exec_ts':t,'raw_entry_5s':v},L)
            if reason is not None:counts[f'{L}x_{reason}']+=1;continue
            if r.observation_id not in out:
                out[r.observation_id]={**e,'second_ref_ts':t,'second_ref_price':v,'eligible_10x':False,'eligible_20x':False}
            else:
                assert out[r.observation_id]['second_ref_ts']==t and np.isclose(out[r.observation_id]['second_ref_price'],v,rtol=1e-12)
            out[r.observation_id][f'eligible_{L}x']=True;counts[f'{L}x_pullback_candidate']+=1
    # If this ever fails, an unknown reference must be retained explicitly,
    # not silently called a noncandidate by the subsequent batch builder.
    assert not unknown,('unavailable_P10',sorted(unknown))
    d=pd.DataFrame(list(out.values())).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
    assert d.observation_id.is_unique and ((d.second_ref_ts>=d.entry_exec_ts+5000)&(d.second_ref_ts+5000<d.quarter_end)).all()
    d.to_parquet(HERE/'短暂回撤事前候选.parquet',index=False)
    bad=s[~s.status.isin(['first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'])]
    info={'base_candidates':len(s),'base_qualified_opportunities':len(base),'candidate_events':len(d),
          'candidate_year_counts':d.source_year.value_counts().to_dict(),
          'candidate_leverage_counts':{'10x':int(d.eligible_10x.sum()),'20x':int(d.eligible_20x.sum())},
          'upstream_unknown_events':len(bad),'unverified_base_paths':meta['unverified_path_count'],
          'unknown_second_reference_events':len(unknown),'filter_counts':dict(counts),
          'plan_sha256':hashlib.sha256((HERE/'冻结研究方案.json').read_bytes()).hexdigest(),
          'source_signal_sha256':hashlib.sha256((ORIG/'动态池逐笔信号筛查.parquet').read_bytes()).hexdigest(),
          'source_path_sha256':hashlib.sha256((ORIG/'动态池延迟市价路径.parquet').read_bytes()).hexdigest(),
          'note':'No old exit/return is used. P10 is a signal, not the fill.'}
    (HERE/'短暂回撤候选质量.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PULLBACK37_CANDIDATES',json.dumps(info,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
