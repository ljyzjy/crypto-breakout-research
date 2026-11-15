"""Reuse independently verified upstream no-order cases for the P10 pullback rule."""
import json
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;F=H.parent/'第三十五轮_二次价格跟随';T=H/'训练期分批'
def main():
    previous=json.loads((F/'严格复核不下单敏感性结果.json').read_text(encoding='utf-8'))
    audit=json.loads((F/'严格复核不下单敏感性独立核验.json').read_text(encoding='utf-8'));assert audit['all_checks_pass']
    signal=pd.read_parquet(T/'动态池逐笔信号筛查.parquet').set_index('observation_id')
    diag=json.loads((T/'不完整数据下单位机会诊断.json').read_text(encoding='utf-8'))
    noorder={x['observation_id'] for x in previous['resolved_source_records']}
    assert len(noorder)==previous['strict_no_order_reconciled']
    assert all(signal.loc[x,'status']=='upstream_data_unknown' for x in noorder)
    out=[]
    for r in diag['rows']:
        if r['period']!='2024_jan_apr':continue
        assert r['possible_unknown_events']>=previous['training_initial_unknown']
        n=r['verified_subset_events'];wins=r['verified_subset_wins'];u=r['possible_unknown_events']-len(noorder)
        out.append({'variant':r['variant'],'verified_events':n,'verified_wins':wins,
          'known_upstream_no_order':len(noorder),'remaining_unknown':u,
          'optimistic_unit_win_rate_upper_pct':100*(wins+u)/(n+u) if n+u else None})
    result={'known_upstream_no_order':len(noorder),'resolved_observation_ids':sorted(noorder),'rows':out,
            'note':'No verified pullback trade or PnL changed; unknown amounts are not imputed. Not a shared-account bound.'}
    (H/'严格复核后回撤敏感性.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PULLBACK37_NO_ORDER_SENSITIVITY',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
