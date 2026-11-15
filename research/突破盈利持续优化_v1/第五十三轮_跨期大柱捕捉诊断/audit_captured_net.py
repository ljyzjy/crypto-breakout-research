"""Reconcile post-close captured-candle net summaries to audited ledgers."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    labels=pd.read_parquet(H/'跨期事后大柱标签.parquet').set_index('observation_id')
    detail=pd.read_parquet(H/'大柱入场后净结果明细.parquet');result=json.loads((H/'大柱入场后净结果.json').read_text(encoding='utf-8'))['rows'];groups=[]
    for year in ('2024','2026'):
        base=pd.read_parquet(I/f'{year}_baseline_ledger.parquet');retry=pd.read_parquet(I/f'{year}_retry_ledger.parquet')
        for mode in ('baseline','single_retest'):
            row=next(x for x in result if x['year']==year and x['strategy']==mode)
            d=detail[(detail.year.astype(str)==year)&detail.strategy.eq(mode)].copy();ledger=pd.concat([base] if mode=='baseline' else [base,retry],ignore_index=True)
            ledger=ledger[ledger.variant.eq('normal_2r_20x')].set_index('observation_id');assert not d.observation_id.duplicated().any()
            for e in d.itertuples(index=False):
                label=labels.loc[e.observation_id];trade=ledger.loc[e.observation_id]
                assert label.status=='verified' and bool(label.large) and int(e.entry_ts)<int(e.quarter_start)+900_000
                assert int(e.entry_ts)==int(trade.entry_ts) and int(e.exit_ts)==int(trade.exit_ts) and int(trade.side)==int(label.allowed_side)
                assert near(e.net,trade.net_per_unit_notional)
            n=len(d);wins=int((d.net>0).sum());assert n==row['captured'] and wins==row['net_wins']
            if n:
                assert near(row['net_win_rate_pct'],100*wins/n) and near(row['mean_net_pct_notional'],100*d.net.mean())
                assert row['held_through_close']==int((d.exit_ts>=d.quarter_start+900_000).sum())
                assert near(row['median_entry_seconds_after_candle_start'],((d.entry_ts-d.quarter_start)/1000).median())
            groups.append({'year':year,'strategy':mode,'captured':n,'net_wins':wins})
    out={'all_checks_pass':True,'groups':groups,'note':'Conditional on future candle close; not an entry signal or strategy-level win rate.'}
    (H/'大柱入场后净结果独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE53_NET_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
