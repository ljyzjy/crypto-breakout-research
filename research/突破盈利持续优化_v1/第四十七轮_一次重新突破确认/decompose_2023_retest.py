"""Describe raw movement, assumed costs and exit causes of 2023 retry paths."""
import json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
def main():
    d=pd.read_parquet(H/'2023重试分批'/'动态池单位收益与风险.parquet')
    rows=[]
    for lev in (10,20):
        g=d[d.variant.eq(f'normal_2r_{lev}x')&d.risk_status.eq('verified')&~d.liq_proxy.fillna(False)].copy()
        if not len(g):continue
        raw=(g.side*(g.exit_raw-g.entry_raw)/g.entry_fill).mean()*100
        slip=(g.side*((g.exit_fill-g.exit_raw)-(g.entry_fill-g.entry_raw))/g.entry_fill).mean()*100
        fee=-(g.entry_fee+g.exit_fee).mean()*100;fund=-g.funding.mean()*100;net=g.net_per_unit_notional.mean()*100
        assert np.isclose(raw+slip+fee+fund,net,rtol=1e-10,atol=1e-12)
        rows.append({'leverage':lev,'verified_added_events':len(g),'wins':int((g.net_per_unit_notional>0).sum()),
                     'mean_raw_movement_pct_notional':float(raw),'mean_slippage_pct_notional':float(slip),
                     'mean_fees_pct_notional':float(fee),'mean_funding_pct_notional':float(fund),
                     'mean_net_pct_notional':float(net),'exit_reasons':g.reason.value_counts().to_dict(),
                     'median_holding_seconds':float(((g.exit_ts-g.entry_ts)/1000).median())})
    out={'rows':rows,'note':'Post-hoc description of added unit paths; actual execution and unknown PnL are not observed.'}
    (H/'2023重试成本分解.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_2023_COSTS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
