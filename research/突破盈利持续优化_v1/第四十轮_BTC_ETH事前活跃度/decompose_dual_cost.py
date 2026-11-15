"""Decompose the frozen selected unit paths into price, slippage, fees and funding."""
import json
from collections import Counter
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
def main():
    d=json.loads((H/'双币活跃度训练诊断.json').read_text(encoding='utf-8'))
    audit=json.loads((H/'双币活跃度独立核验.json').read_text(encoding='utf-8'));assert audit['all_checks_pass']
    ledger=pd.read_parquet(I/'baseline_ledger.parquet');output=[]
    for z in d['rows']:
        L=z['leverage'];ids=set(z['verified_observation_ids']);g=ledger[ledger.variant.eq(f'normal_2r_{L}x')&ledger.observation_id.isin(ids)]
        assert len(g)==len(ids)==z['verified_events'];parts=[]
        for r in g.itertuples(index=False):
            side=int(r.side);unit=float(r.entry_fill)
            raw=side*(r.exit_raw-r.entry_raw)/unit
            slip=side*((r.exit_fill-r.exit_raw)-(r.entry_fill-r.entry_raw))/unit
            fees=-(r.entry_fee+r.exit_fee);funding=-r.funding;net=raw+slip+fees+funding
            assert abs(net-r.net_per_unit_notional)<1e-10
            parts.append((raw,slip,fees,funding,net))
        a=np.array(parts,float);x=a[:,4];wins=x[x>0];loss=-x[x<0]
        out={'leverage':L,'verified_events':len(a),'mean_raw_price_movement_pct_notional':float(100*a[:,0].mean()),
             'mean_slippage_pct_notional':float(100*a[:,1].mean()),'mean_fees_pct_notional':float(100*a[:,2].mean()),
             'mean_funding_pct_notional':float(100*a[:,3].mean()),'mean_net_pct_notional':float(100*a[:,4].mean()),
             'average_winning_net_pct_notional':float(100*wins.mean()) if len(wins) else None,
             'average_losing_net_pct_notional':float(100*loss.mean()) if len(loss) else None,
             'break_even_win_rate_at_observed_mean_win_loss_pct':float(100*loss.mean()/(loss.mean()+wins.mean())) if len(loss) and len(wins) else None,
             'exit_reasons':dict(Counter(g.reason))}
        output.append(out)
    result={'period':'2024_jan_apr','rows':output,
            'note':'Same selected known unit paths only. Components do not estimate real execution; unknown outcomes remain unknown.'}
    (H/'双币过滤成本分解.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL40_COST_DECOMPOSITION',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
