"""A single frozen, causal phase filter on a previously settled training batch."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
TRAIN=HERE/'冻结输入'
SOURCE_FILES=['动态池逐笔信号筛查.parquet','动态池单位收益与风险.parquet',
              '不完整数据下单位机会诊断.json','动态池净账本独立核验.json']

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def describe(d,unknown):
    n=len(d);x=d.net_pct_notional.to_numpy(float);assert np.isfinite(x).all()
    wins=int((x>0).sum());pos=float(x[x>0].sum());neg=float(-x[x<0].sum())
    return {'verified_events':n,'wins':wins,'win_rate_pct':100*wins/n if n else None,
            'mean_net_pct_notional':float(x.mean()) if n else None,
            'profit_factor':pos/neg if neg else None,'potential_unknown_events':unknown,
            'optimistic_unit_win_rate_upper_pct':100*(wins+unknown)/(n+unknown) if n+unknown else None}

def main():
    frozen=json.loads((HERE/'输入文件冻结哈希.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256']==sha(HERE/'冻结研究方案.md')
    assert frozen['source_sha256']=={name:sha(TRAIN/name) for name in SOURCE_FILES}
    s=pd.read_parquet(TRAIN/SOURCE_FILES[0]);p=pd.read_parquet(TRAIN/SOURCE_FILES[1])
    q=json.loads((TRAIN/SOURCE_FILES[2]).read_text(encoding='utf-8'))
    assert not q['whole_screen_complete'] and s.observation_id.is_unique
    assert not p.duplicated(['observation_id','variant']).any()
    known={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    unknown=int((~s.status.isin(known)).sum())
    out=[]
    for L in (10,20):
        name=f'normal_2r_{L}x';r=p[p.variant.eq(name)].copy()
        diag=next(z for z in q['rows'] if z['period']=='2024_jan_apr' and z['variant']==name)
        assert len(r)==diag['verified_subset_events'] and unknown==diag['possible_unknown_events']
        assert r.status.eq('verified').all() and r.risk_status.eq('verified').all() and not r.liq_proxy.any()
        r=r.merge(s[['observation_id','status','decision_ts','quarter_start']],on='observation_id',
                  how='left',validate='one_to_one',suffixes=('','_signal'))
        assert r.status_signal.eq('qualified').all() and r.decision_ts_signal.notna().all()
        assert (r.decision_ts==r.decision_ts_signal).all()
        dt=r.decision_ts_signal-r.quarter_start
        assert (dt>=0).all() and (dt<900_000).all()
        retained=r[dt>=10_000];removed=r[dt<10_000]
        assert len(retained)+len(removed)==len(r)
        assert (r.entry_ts>=r.decision_ts+10_000).all()
        original=describe(r,unknown);after=describe(retained,unknown);excluded=describe(removed,0)
        assert original['wins']==diag['verified_subset_wins']
        assert abs(original['mean_net_pct_notional']-diag['verified_subset_mean_net_pct_notional'])<1e-10
        out.append({'leverage':L,'original':original,'excluded_early_known_only':excluded,
                    'phase_filter':after,'screen_complete':False,'acceptance_pass':False})
    result={'period':'2024-01-01 through 2024-04-30 UTC, with quarter-end + 60 seconds embargo',
            'source_hashes':frozen,'rows':out,
            'note':'Unresolved candidates conservatively stay unknown for both variants; no account or full-period PnL inferred.'}
    (HERE/'首十秒过滤训练诊断.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
