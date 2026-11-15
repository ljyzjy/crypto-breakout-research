"""Measure realized model losses versus the signal-time planned risk budget."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def main():
    bulk.runner.guard(start=True)
    specs=[('baseline',R98,'original'),('cost_gate',P/'第九十九轮_成本相对波幅门','original'),('time_stop',P/'第一百轮_突破无进展提前退出','time_stop')]
    results=[];details=[]
    for name,folder,period in specs:
        summary=json.loads((folder/'共享钱包情景汇总.json').read_text(encoding='utf-8'));audit=json.loads((folder/'共享钱包独立核验.json').read_text(encoding='utf-8'))
        assert audit['all_checks_pass'] and audit['result_sha256']==bulk.sha(folder/'共享钱包情景汇总.json')
        path=folder/'共享钱包情景逐笔.csv';assert summary['outcomes_sha256']==bulk.sha(path)
        with path.open(encoding='utf-8',newline='') as f:source=list(csv.DictReader(f))
        for lev in (10,20):
            rows=[r for r in source if r['period']==period and r['cohort']=='base' and int(r['leverage'])==lev and r['reverse_ties']=='False' and r['status']=='closed']
            fractions=[];over_plan=0;over_half=0
            for r in rows:
                wallet=D(r['reference_wallet']);pnl=D(r['net_pnl']);planned=D(r['planned_risk']);assert wallet>0 and planned>=0
                fraction=-100*pnl/wallet;fractions.append(fraction)
                over_half+=fraction>D('.5');over_plan+= -pnl>planned
                details.append({'strategy':name,'leverage':lev,'observation_id':r['observation_id'],'reference_wallet':str(wallet),
                                'net_pnl':str(pnl),'planned_risk':str(planned),'loss_pct_reference_wallet':str(fraction),
                                'exceeds_half_pct':fraction>D('.5'),'exceeds_planned':-pnl>planned})
            expected=next(x for x in summary['rows'] if x['period']==period and x['cohort']=='base' and x['leverage']==lev and not x['reverse_ties'])
            assert len(rows)==expected['simulated_trades']
            results.append({'strategy':name,'leverage':lev,'closed_trades':len(rows),'losses_over_half_pct_wallet':over_half,
                            'losses_over_planned_risk':over_plan,'worst_loss_pct_reference_wallet':float(max(fractions)) if fractions else None})
    with (H/'计划风险超额逐笔.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(details[0]));w.writeheader();w.writerows(details)
    out={'rows':results,'detail_sha256':bulk.sha(H/'计划风险超额逐笔.csv'),'code_sha256':bulk.sha(Path(__file__)),
         'wallet_audit_sha256':{n:bulk.sha(folder/'共享钱包独立核验.json') for n,folder,_ in specs},
         'note':'Modeled closed trades only; reference-wallet loss is not floating equity drawdown or a guaranteed stop.'}
    (H/'计划风险超额汇总.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT103_RESULTS',json.dumps(results,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
