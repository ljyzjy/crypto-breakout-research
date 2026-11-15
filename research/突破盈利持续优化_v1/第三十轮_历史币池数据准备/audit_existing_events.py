"""Independently check the old-event historical-rank merge and all reported scores."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
def main():
    ranks=pd.read_parquet(HERE/'历史动态20币候选_仅数据排名.parquet')
    matched=pd.read_parquet(HERE/'旧18币秒级机会_历史排名匹配.parquet')
    origin=pd.read_parquet(PARENT/'第二十九轮_秒级延迟与失败退出'/'秒级净收益与风险核算.parquet')
    original=origin[origin.variant.isin(['normal_2r','fast_2r'])].set_index(['observation_id','variant'])
    assert len(matched)==len(original) and not matched.duplicated(['observation_id','variant']).any()
    membership={(r.day,r.symbol):int(r.rank) for r in ranks.itertuples(index=False)}
    selected=0
    for r in matched.itertuples(index=False):
        expected=membership.get((r.day,r.contract))
        assert bool(r.in_past_volume_top20)==(expected is not None)
        if expected is not None:assert int(r.rank)==expected;selected+=1
        prior=original.loc[(r.observation_id,r.variant)]
        assert int(prior.decision_ts)==int(r.decision_ts)
        assert abs(float(prior.net_per_unit_notional)-float(r.net_per_unit_notional))<1e-14
    report=json.loads((HERE/'旧机会历史流动性筛查结果.json').read_text(encoding='utf-8'))
    assert report['plan_sha256']==hashlib.sha256((HERE/'旧机会历史流动性筛查计划.json').read_bytes()).hexdigest()
    assert report['source_rank_sha256']==hashlib.sha256((HERE/'历史动态20币候选_仅数据排名.parquet').read_bytes()).hexdigest()
    cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    val=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000)
    periods={'2024_jan_apr_train':matched.source_year.eq('2024')&(matched.quarter_end+60_000<=cutoff),
             '2024_may_jun_later':matched.source_year.eq('2024')&matched.decision_ts.ge(val),
             '2026_may_jul_seen':matched.source_year.eq('2026')}
    for s in report['comparisons']:
        ok=periods[s['period']]&matched.variant.eq(s['variant'])
        if s['subset']=='historical_top20_within_old_18':ok&=matched.in_past_volume_top20
        subset=matched[ok];x=subset.net_per_unit_notional.to_numpy(float);win=x[x>0];loss=x[x<0]
        assert s['opportunities']==len(x) and s['net_wins']==len(win) and s['opportunity_days_utc']==subset.day.nunique()
        if len(x):assert abs(s['net_win_rate_pct']-100*len(win)/len(x))<1e-10 and abs(s['avg_net_pct_notional']-100*x.mean())<1e-10
        if len(loss):assert abs(s['profit_factor']-win.sum()/-loss.sum())<1e-10
    out={'checked_variant_paths':len(matched),'top20_variant_paths':selected,'comparison_rows':len(report['comparisons']),
         'all_rank_memberships_and_source_values_match':True,'frozen_plan_and_rank_hashes_match':True,
         'note':'Historical units within the old fixed 18 pool; not a complete dynamic-universe or shared-account test.'}
    (HERE/'旧机会历史排名筛查独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE30_EXISTING_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
