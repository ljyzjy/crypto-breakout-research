"""Apply pre-frozen daily volume membership to previously replayed paths."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
def metrics(g):
    x=g.net_per_unit_notional.to_numpy(float);wins=x[x>0];loss=x[x<0]
    return {'opportunities':len(x),'net_wins':len(wins),'net_win_rate_pct':float(100*len(wins)/len(x)) if len(x) else None,
            'avg_net_pct_notional':float(100*x.mean()) if len(x) else None,
            'profit_factor':float(wins.sum()/-loss.sum()) if len(loss) else None,
            'opportunity_days_utc':int(g.day.nunique())}
def main():
    quality=json.loads((HERE/'历史动态币池数据质量.json').read_text(encoding='utf-8'))
    index_quality=json.loads((HERE/'历史日线索引清点.json').read_text(encoding='utf-8'))
    assert not quality['archive_errors'] and not index_quality['symbol_errors'],'unresolved archive errors prevent comparison'
    rank=pd.read_parquet(HERE/'历史动态20币候选_仅数据排名.parquet')
    assert not rank.duplicated(['day','symbol']).any() and rank['rank'].between(1,20).all()
    r29=PARENT/'第二十九轮_秒级延迟与失败退出'
    integrity=json.loads((r29/'秒级筛查完整性.json').read_text(encoding='utf-8'));assert integrity['complete']
    data=pd.read_parquet(r29/'秒级净收益与风险核算.parquet')
    data=data[data.variant.isin(['normal_2r','fast_2r'])].copy()
    data['day']=pd.to_datetime(data.decision_ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    assert set(data.day).issubset(set(rank.day)),'missing historical rank day'
    data=data.merge(rank[['day','symbol','rank','past_30d_quote']],left_on=['day','contract'],right_on=['day','symbol'],how='left',
                    validate='many_to_one',suffixes=('','_rank'))
    data['in_past_volume_top20']=data['rank'].notna()
    cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    valid_from=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000)
    masks={'2024_jan_apr_train':data.source_year.eq('2024')&(data.quarter_end+60_000<=cutoff),
           '2024_may_jun_later':data.source_year.eq('2024')&data.decision_ts.ge(valid_from),
           '2026_may_jul_seen':data.source_year.eq('2026')}
    out=[]
    for period,mask in masks.items():
        for variant in ('normal_2r','fast_2r'):
            for subset in ('all_old_18_opportunities','historical_top20_within_old_18'):
                chosen=mask&data.variant.eq(variant)
                if subset=='historical_top20_within_old_18':chosen&=data.in_past_volume_top20
                out.append({'period':period,'variant':variant,'subset':subset,**metrics(data[chosen])})
    data.to_parquet(HERE/'旧18币秒级机会_历史排名匹配.parquet',index=False)
    report={'comparisons':out,'plan_sha256':hashlib.sha256((HERE/'旧机会历史流动性筛查计划.json').read_bytes()).hexdigest(),
            'source_rank_sha256':hashlib.sha256((HERE/'历史动态20币候选_仅数据排名.parquet').read_bytes()).hexdigest(),
            'note':'Historical time-ordered subset of preselected 18 only; unit opportunities, no account performance, not a dynamic-universe backtest.'}
    (HERE/'旧机会历史流动性筛查结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE30_OLD_EVENT_DIAGNOSTIC',json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
