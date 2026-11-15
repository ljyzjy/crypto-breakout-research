"""Describe validated paths and worst/best win-count scenarios without imputing PnL."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent
def main():
    quality=json.loads((HERE/'动态池单位筛查完整性.json').read_text(encoding='utf-8'))
    signal=pd.read_parquet(HERE/'动态池逐笔信号筛查.parquet');paths=pd.read_parquet(HERE/'动态池延迟市价路径.parquet')
    ledger=pd.read_parquet(HERE/'动态池单位收益与风险.parquet')
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified','no_follow_known'}
    cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000);later=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000)
    periods={'2024_jan_apr':lambda f:f.source_year.eq('2024')&(f.quarter_end+60_000<=cutoff),
             '2024_may_jun':lambda f:f.source_year.eq('2024')&f.trigger_minute.ge(later),
             '2026_may_jul':lambda f:f.source_year.eq('2026')}
    # Path/ledger inherit the candidate clock solely for classifying period.
    clock=signal[['observation_id','trigger_minute']]
    paths=paths.merge(signal[['observation_id','source_year','quarter_end','trigger_minute']],on='observation_id',validate='many_to_one')
    ledger=ledger.merge(clock,on='observation_id',validate='many_to_one')
    output=[]
    for period,fn in periods.items():
      s=signal[fn(signal)];p=paths[fn(paths)];l=ledger[fn(ledger)]
      source_unknown=set(s.loc[~s.status.isin(benign),'observation_id'])
      for variant in ('normal_2r_10x','fast_2r_10x','normal_2r_20x','fast_2r_20x'):
        pp=p[p.variant.eq(variant)];ll=l[l.variant.eq(variant)].copy()
        risk_ok=ll.risk_status.eq('verified')&~ll.liq_proxy.fillna(False)
        good=ll[risk_ok];unknown=source_unknown|set(pp.loc[~pp.status.eq('verified'),'observation_id'])|set(ll.loc[~risk_ok,'observation_id'])
        known=set(good.observation_id);unknown-=known
        x=good.net_per_unit_notional.to_numpy(float);wins=int((x>0).sum());pos=float(x[x>0].sum());neg=float(-x[x<0].sum());total=len(x)+len(unknown)
        output.append({'period':period,'variant':variant,'verified_subset_events':len(x),'verified_subset_wins':wins,
          'verified_subset_win_rate_pct':float(100*wins/len(x)) if len(x) else None,
          'verified_subset_mean_net_pct_notional':float(100*x.mean()) if len(x) else None,
          'verified_subset_profit_factor':pos/neg if neg else None,'possible_unknown_events':len(unknown),
          'unit_win_rate_lower_pct':float(100*wins/total) if total else None,
          'unit_win_rate_upper_pct':float(100*(wins+len(unknown))/total) if total else None})
    out={'whole_screen_complete':quality['complete'],'rows':output,
         'rule_sha256':hashlib.sha256((HERE/'不完整数据敏感性规则.json').read_bytes()).hexdigest(),
         'note':'Descriptive selected subset and extreme win-count bounds only; no overall PnL or shared-account inference.'}
    (HERE/'不完整数据下单位机会诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_PARTIAL_DIAGNOSTIC',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
