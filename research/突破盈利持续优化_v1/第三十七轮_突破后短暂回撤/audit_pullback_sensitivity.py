"""Verify no-order provenance and upper bounds without modifying path outcomes."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;F=H.parent/'第三十五轮_二次价格跟随';T=H/'训练期分批'
def main():
    x=json.loads((H/'严格复核后回撤敏感性.json').read_text(encoding='utf-8'))
    prior=json.loads((F/'严格复核不下单敏感性结果.json').read_text(encoding='utf-8'))
    audit=json.loads((F/'严格复核不下单敏感性独立核验.json').read_text(encoding='utf-8'))
    d=json.loads((T/'不完整数据下单位机会诊断.json').read_text(encoding='utf-8'))
    s=pd.read_parquet(T/'动态池逐笔信号筛查.parquet').set_index('observation_id')
    ids=set(x['resolved_observation_ids']);assert audit['all_checks_pass']
    assert ids=={r['observation_id'] for r in prior['resolved_source_records']}
    assert len(ids)==x['known_upstream_no_order'] and all(s.loc[v,'status']=='upstream_data_unknown' for v in ids)
    for row in x['rows']:
        p=next(z for z in d['rows'] if z['period']=='2024_jan_apr' and z['variant']==row['variant'])
        assert row['verified_events']==p['verified_subset_events'] and row['verified_wins']==p['verified_subset_wins']
        assert row['remaining_unknown']==p['possible_unknown_events']-len(ids)
        expected=100*(row['verified_wins']+row['remaining_unknown'])/(row['verified_events']+row['remaining_unknown'])
        assert math.isclose(expected,row['optimistic_unit_win_rate_upper_pct'],rel_tol=1e-12)
    out={'resolved_no_order_checked':len(ids),'bounds_checked':len(x['rows']),'all_checks_pass':True,
         'note':'Only already-verified no-order provenance is reused; unknown PnL is not filled in.'}
    (H/'回撤敏感性独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PULLBACK37_SENSITIVITY_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
