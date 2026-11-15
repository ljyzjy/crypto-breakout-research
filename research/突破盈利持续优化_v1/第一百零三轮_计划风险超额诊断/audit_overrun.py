"""Independently cross-check every closed wallet row and risk-overrun aggregate."""
import json
import math
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def main():
    bulk.runner.guard(start=True);out=json.loads((H/'计划风险超额汇总.json').read_text(encoding='utf-8'))
    assert out['code_sha256']==bulk.sha(H/'risk_overrun.py') and out['detail_sha256']==bulk.sha(H/'计划风险超额逐笔.csv')
    detail=pd.read_csv(H/'计划风险超额逐笔.csv');checked=0
    for name,folder,period in [('baseline',R98,'original'),('cost_gate',P/'第九十九轮_成本相对波幅门','original'),('time_stop',P/'第一百轮_突破无进展提前退出','time_stop')]:
        original=pd.read_csv(folder/'共享钱包情景逐笔.csv')
        for lev in (10,20):
            a=original[(original.period==period)&(original.cohort=='base')&(original.leverage==lev)&(~original.reverse_ties)&(original.status=='closed')].set_index('observation_id')
            b=detail[(detail.strategy==name)&(detail.leverage==lev)].set_index('observation_id');assert len(a)==len(b) and set(a.index)==set(b.index)
            ratio=-100*a.net_pnl/a.reference_wallet;planned=(-a.net_pnl>a.planned_risk)
            assert ((ratio-b.loss_pct_reference_wallet).abs()<1e-9).all()
            assert ((ratio>.5)==b.exceeds_half_pct).all() and (planned==b.exceeds_planned).all()
            row=next(x for x in out['rows'] if x['strategy']==name and x['leverage']==lev)
            assert row['closed_trades']==len(a) and row['losses_over_half_pct_wallet']==int((ratio>.5).sum())
            assert row['losses_over_planned_risk']==int(planned.sum())
            assert math.isclose(row['worst_loss_pct_reference_wallet'],float(ratio.max()),rel_tol=1e-9,abs_tol=1e-10)
            checked+=len(a)
    audit={'all_checks_pass':True,'closed_trade_rows_checked':checked,'scenarios_checked':len(out['rows']),
           'result_sha256':bulk.sha(H/'计划风险超额汇总.json'),'code_sha256':bulk.sha(Path(__file__)),
           'note':'Counts model losses versus signal-time wallet and planned risk; not full equity drawdown.'}
    (H/'风险超额独立核验.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT103_AUDIT',checked,flush=True)


if __name__=='__main__':main()
