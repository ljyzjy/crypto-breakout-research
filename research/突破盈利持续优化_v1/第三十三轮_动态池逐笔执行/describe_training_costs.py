"""Reconcile gross reference movement, modeled costs, funding and unit net PnL."""
import json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
def main():
    sources={'strict':HERE/'训练期分批'/'动态池单位收益与风险.parquet',
             'backup':PARENT/'第三十四轮_历史候选动态替补'/'训练期分批'/'动态池单位收益与风险.parquet'}
    rows=[]
    for label,path in sources.items():
        d=pd.read_parquet(path)
        for variant,g in d.groupby('variant'):
            g=g[g.risk_status.eq('verified')&~g.liq_proxy.fillna(False)];qty=1/g.entry_fill
            gross=g.side*qty*(g.exit_raw-g.entry_raw);slip=.0005*qty*(g.entry_raw+g.exit_raw)
            fee=g.entry_fee+g.exit_fee;fund=g.funding;net=gross-slip-fee-fund
            assert np.max(np.abs(net-g.net_per_unit_notional))<1e-12
            rows.append({'pool':label,'variant':variant,'verified_unit_events':len(g),
                'gross_reference_pct':float(100*gross.mean()),'slippage_cost_pct':float(100*slip.mean()),
                'fee_cost_pct':float(100*fee.mean()),'funding_cost_pct':float(100*fund.mean()),
                'net_pct_notional':float(100*net.mean())})
    out={'rows':rows,'note':'Verified unit subset only; missing/ambiguous events and account sizing are not represented.'}
    (HERE/'训练期已核验机会成本分解.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_TRAIN_COST_DECOMPOSITION',json.dumps(rows,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
