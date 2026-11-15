"""Post-hoc descriptive cost/timing decomposition; not a selection rule."""
import json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent
def main():
    d=pd.read_parquet(HERE/'秒级净收益与风险核算.parquet')
    cut=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    val=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000)
    periods={'train_2024_jan_apr':d.source_year.eq('2024')&(d.quarter_end+60_000<=cut),
             'later_2024_may_jun':d.source_year.eq('2024')&d.decision_ts.ge(val),
             'seen_2026_may_jul':d.source_year.eq('2026')}
    rows=[];pairs=[]
    for period,mask in periods.items():
      for v in ['normal_1r','fast_1r','normal_2r','fast_2r']:
        z=d[mask&d.variant.eq(v)].copy();qty=1/z.entry_fill
        gross=(z.side*qty*(z.exit_raw-z.entry_raw));slip=.0005*qty*(z.entry_raw+z.exit_raw)
        fees=z.entry_fee+z.exit_fee
        assert np.max(np.abs(gross-slip-fees-z.funding-z.net_per_unit_notional))<1e-12
        rows.append({'period':period,'variant':v,'opportunities':len(z),'reason_counts':z.reason.value_counts().to_dict(),
                     'mean_gross_raw_pct_notional':float(100*gross.mean()),'mean_slippage_pct_notional':float(100*slip.mean()),
                     'mean_fees_pct_notional':float(100*fees.mean()),'mean_funding_pct_notional':float(100*z.funding.mean()),
                     'mean_net_pct_notional':float(100*z.net_per_unit_notional.mean()),
                     'median_trigger_to_entry_seconds':float((z.entry_ts-z.decision_ts).median()/1000),
                     'p95_trigger_to_entry_seconds':float((z.entry_ts-z.decision_ts).quantile(.95)/1000),
                     'median_holding_seconds':float((z.exit_ts-z.entry_ts).median()/1000)})
      for multiple in ('1r','2r'):
        normal=d[mask&d.variant.eq('normal_'+multiple)].set_index('observation_id')
        fast=d[mask&d.variant.eq('fast_'+multiple)].set_index('observation_id')
        delta=fast.net_per_unit_notional.sub(normal.net_per_unit_notional)
        assert delta.notna().all()
        pairs.append({'period':period,'multiple':multiple,'paired_opportunities':len(delta),
                      'fast_better_count':int((delta>1e-12).sum()),'fast_worse_count':int((delta< -1e-12).sum()),
                      'fast_same_count':int((abs(delta)<=1e-12).sum()),'mean_fast_minus_normal_pct_notional':float(100*delta.mean())})
    out={'descriptive_cost_and_reasons':rows,'paired_fast_vs_normal':pairs,
         'note':'After-the-fact explanations only; no new trading filter or statistical significance claim.'}
    (HERE/'秒级成本与配对诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SECONDS29_DESCRIPTION',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
