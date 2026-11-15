"""Reconcile raw price move, assumed slippage, fees and funding on fixed paths."""
import hashlib,json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;R=P/'第四十七轮_一次重新突破确认';I=P/'第四十九轮_固定主动方向强度'/'冻结输入'
def main():
    comp=json.loads((R/'单次重试跨期单位对照.json').read_text(encoding='utf-8'))['rows']
    assert json.loads((R/'单次重试净账本独立核验.json').read_text(encoding='utf-8'))['all_checks_pass'];out=[]
    frozen=json.loads((I.parent/'输入冻结哈希.json').read_text(encoding='utf-8'))
    for name,digest in frozen['inputs'].items():assert hashlib.sha256((I/name).read_bytes()).hexdigest()==digest
    for year in ('2023','2024','2026'):
        l=pd.concat([pd.read_parquet(I/f'{year}_baseline_ledger.parquet'),pd.read_parquet(I/f'{year}_retry_ledger.parquet')],ignore_index=True)
        for lev in (10,20):
            summary=next(x for x in comp if x['year']==year and x['leverage']==lev and x['strategy']=='single_retest')
            g=l[l.variant.eq(f'normal_2r_{lev}x')&l.observation_id.isin(summary['verified_observation_ids'])].copy()
            assert g.observation_id.is_unique and set(g.observation_id)==set(summary['verified_observation_ids'])
            for r in g.itertuples(index=False):
                gross=int(r.side)*(float(r.exit_raw)-float(r.entry_raw))/float(r.entry_fill)
                slip=int(r.side)*((float(r.exit_fill)-float(r.entry_fill))-(float(r.exit_raw)-float(r.entry_raw)))/float(r.entry_fill)
                fees=-float(r.entry_fee)-float(r.exit_fee);fund=-float(r.funding)
                assert math.isclose(gross+slip+fees+fund,float(r.net_per_unit_notional),rel_tol=1e-10,abs_tol=1e-11)
            gross=g.side*(g.exit_raw-g.entry_raw)/g.entry_fill
            slip=g.side*((g.exit_fill-g.entry_fill)-(g.exit_raw-g.entry_raw))/g.entry_fill
            fee=-g.entry_fee-g.exit_fee;fund=-g.funding;net=g.net_per_unit_notional
            assert math.isclose(100*net.mean(),summary['mean_net_pct_notional'],rel_tol=1e-10,abs_tol=1e-11)
            out.append({'year':year,'leverage':lev,'verified_events':len(g),'unknown_events':summary['possible_unknown_events'],
                        'mean_raw_direction_pct_notional':100*float(gross.mean()),'mean_slippage_pct_notional':100*float(slip.mean()),
                        'mean_fees_pct_notional':100*float(fee.mean()),'mean_funding_pct_notional':100*float(fund.mean()),
                        'mean_net_pct_notional':100*float(net.mean()),'exit_reasons':g.reason.value_counts().to_dict(),
                        'note':'Gross uses public trade reference prices; slippage and fees are modeled, not observed fills.'})
    (H/'跨期成本分解.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('COST52_DECOMPOSITION',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
