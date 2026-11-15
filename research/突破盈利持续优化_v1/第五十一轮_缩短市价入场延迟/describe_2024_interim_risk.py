"""Measure the worst verified 20x opportunity in the frozen interim batch."""
import hashlib,json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'2024中间批次_31候选'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    frozen=json.loads((I/'中间快照哈希.json').read_text(encoding='utf-8'));assert frozen['all_checks_pass']
    for n,v in frozen['files'].items():assert sha(I/n)==v
    detail=pd.read_parquet(I/'2024一秒五秒逐笔配对结果.parquet');d=detail[detail.leverage.eq(20)].copy();assert len(d)==30
    worst=d.loc[d.one_second_net.idxmin()];ledger=pd.read_parquet(I/'动态池单位收益与风险.parquet')
    rows=ledger[ledger.variant.eq('one_second_2r_20x')&ledger.observation_id.eq(worst.observation_id)];assert len(rows)==1
    x=rows.iloc[0];assert x.risk_status=='verified' and not bool(x.liq_proxy)
    assert math.isclose(float(x.net_per_unit_notional),float(worst.one_second_net),rel_tol=1e-11,abs_tol=1e-12)
    out={'year':'2024','leverage':20,'verified_paired_trades':len(d),'worst_observation_id':worst.observation_id,
         'worst_net_pct_entry_notional':100*float(worst.one_second_net),
         'worst_net_pct_initial_isolated_margin_at_exact_20x':2000*float(worst.one_second_net),
         'exit_reason':x.reason,'liquidation_proxy':bool(x.liq_proxy),
         'note':'Pure arithmetic with initial margin=entry notional/20; not an account drawdown or observed fill.'}
    (H/'2024中间批次_单笔风险诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENTRY51_2024_INTERIM_TAIL',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
