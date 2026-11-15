"""Freeze causal P10 continuation candidates using entry-reference fields only."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ORIG=PARENT/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(ORIG))
from leveraged_paths import known_precheck
def main():
    s=pd.read_parquet(ORIG/'动态池逐笔信号筛查.parquet');p=pd.read_parquet(ORIG/'动态池延迟市价路径.parquet')
    meta=json.loads((ORIG/'动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    assert s.observation_id.is_unique and not p.duplicated(['observation_id','variant']).any()
    base=s[s.status.eq('qualified')].set_index('observation_id');out={};counts=Counter();unknown_entry_ids=set()
    for L in (10,20):
        # Only entry reference time/price from the old path are used; no old
        # reason, exit, funding or PnL may influence the new candidate rule.
        # Do not gate on old exit status: future exit availability was not
        # known at P10. If an entry reference is absent, retain it as unknown.
        q=p[p.variant.eq(f'normal_2r_{L}x')][['observation_id','entry_ts','entry_raw']]
        for row in q.itertuples(index=False):
            if pd.isna(row.entry_ts) or pd.isna(row.entry_raw):
                unknown_entry_ids.add(row.observation_id);counts[f'{L}x_missing_second_reference']+=1;continue
            e=base.loc[row.observation_id].to_dict();e['observation_id']=row.observation_id
            t10=int(row.entry_ts);v10=float(row.entry_raw);t5=int(e['entry_exec_ts']);v5=float(e['raw_entry_5s'])
            assert t10>=t5+5000 and t10<int(e['quarter_end'])
            if int(e['side'])*(v10-v5)<=0:counts[f'{L}x_no_follow']+=1;continue
            at_t10={**e,'entry_exec_ts':t10,'raw_entry_5s':v10};reason=known_precheck(at_t10,L)
            if reason is not None:counts[f'{L}x_{reason}']+=1;continue
            if row.observation_id not in out:
                out[row.observation_id]={**e,'second_ref_ts':t10,'second_ref_price':v10,'eligible_10x':False,'eligible_20x':False}
            else:
                assert out[row.observation_id]['second_ref_ts']==t10 and np.isclose(out[row.observation_id]['second_ref_price'],v10,rtol=1e-12)
            out[row.observation_id][f'eligible_{L}x']=True;counts[f'{L}x_follow_candidate']+=1
    d=pd.DataFrame(list(out.values())).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
    assert d.observation_id.is_unique and ((d.second_ref_ts>=d.entry_exec_ts+5000)&(d.second_ref_ts+5000<d.quarter_end)).all()
    d.to_parquet(HERE/'二次跟随事前候选.parquet',index=False)
    unknown=s[~s.status.isin(['first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'])]
    summary={'base_candidates':len(s),'base_qualified_opportunities':len(base),'new_candidate_events':len(d),
             'candidate_year_counts':d.source_year.value_counts().to_dict(),'candidate_leverage_counts':{'10x':int(d.eligible_10x.sum()),'20x':int(d.eligible_20x.sum())},
             'base_source_unknown_events':len(unknown),'unverified_base_paths':meta['unverified_path_count'],
             'unknown_second_reference_events':len(unknown_entry_ids),
             'filter_counts':dict(counts),'plan_sha256':hashlib.sha256((HERE/'冻结研究方案.json').read_bytes()).hexdigest(),
             'source_signal_sha256':hashlib.sha256((ORIG/'动态池逐笔信号筛查.parquet').read_bytes()).hexdigest(),
             'source_path_sha256':hashlib.sha256((ORIG/'动态池延迟市价路径.parquet').read_bytes()).hexdigest(),
             'note':'No exit/return label is used. P10 is an observed signal, not an entry fill; 5s more latency and risk checks remain.'}
    (HERE/'二次跟随候选质量.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FOLLOW35_CANDIDATES',json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
