"""Describe 2023 verified unit paths and optimistic win-count bounds only."""
import json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;OUT=H/'部分批次'
def main():
    quality=json.loads((OUT/'动态池单位筛查完整性.json').read_text(encoding='utf-8'))
    signal=pd.read_parquet(OUT/'动态池逐笔信号筛查.parquet');paths=pd.read_parquet(OUT/'动态池延迟市价路径.parquet')
    ledger=pd.read_parquet(OUT/'动态池单位收益与风险.parquet')
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    source_unknown=set(signal.loc[~signal.status.isin(benign),'observation_id']);rows=[]
    for variant in ('normal_2r_10x','fast_2r_10x','normal_2r_20x','fast_2r_20x'):
        p=paths[paths.variant.eq(variant)];l=ledger[ledger.variant.eq(variant)]
        liq=l.liq_proxy.fillna(False) if 'liq_proxy' in l else pd.Series(False,index=l.index)
        ok=l.risk_status.eq('verified')&~liq;good=l[ok]
        unknown=source_unknown|set(p.loc[~p.status.eq('verified'),'observation_id'])|set(l.loc[~ok,'observation_id'])
        unknown-=set(good.observation_id)
        x=good.net_per_unit_notional.to_numpy(float);n=len(x);wins=int((x>0).sum());u=len(unknown)
        pos=float(x[x>0].sum());neg=float(-x[x<0].sum())
        rows.append({'period':'2023','variant':variant,'verified_subset_events':n,'verified_subset_wins':wins,
                     'verified_subset_win_rate_pct':100*wins/n if n else None,
                     'verified_subset_mean_net_pct_notional':float(100*x.mean()) if n else None,
                     'verified_subset_profit_factor':pos/neg if neg else None,'possible_unknown_events':u,
                     'unit_win_rate_lower_pct':100*wins/(n+u) if n+u else None,
                     'unit_win_rate_upper_pct':100*(wins+u)/(n+u) if n+u else None})
    out={'whole_screen_complete':quality['complete'],'rows':rows,
         'note':'Fixed 11-coin survivorship-biased pool; missing source cases unknown, no account outcome or independent forward validation.'}
    (OUT/'2023不完整数据下单位诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_UNIT_DIAGNOSIS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
