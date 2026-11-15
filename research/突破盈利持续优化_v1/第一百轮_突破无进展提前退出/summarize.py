"""Report paired audited raw paths for the fixed progress exit."""
from decimal import Decimal
import json
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';B=R98/'原始逐笔批次';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk
from summarize import metric


def main():
    bulk.runner.guard(start=True)
    audit=json.loads((H/'进展退出独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['ledger_sha256']==bulk.sha(H/'进展退出单位账本.parquet') and audit['code_sha256']==bulk.sha(H/'audit_exit.py')
    original=pd.read_parquet(B/'单位净收益与风险.parquet').set_index(['observation_id','variant']).to_dict('index')
    current=pd.read_parquet(H/'进展退出单位账本.parquet').to_dict('records')
    baseline_summary=json.loads((R98/'原始逐笔汇总.json').read_text(encoding='utf-8'))
    out=[];changes=[]
    for lev in (10,20):
        variant=f'one_observation_2r_{lev}x';subset=[r for r in current if r['variant']==variant]
        pairs=[r for r in subset if r['risk_status']=='verified' and not bool(r['liq_proxy'])]
        base=[];new=[];diffs=[]
        for r in pairs:
            orig=original[(r['observation_id'],variant)]
            for src,dest in ((orig,base),(r,new)):
                dest.append({'entry_ts':int(src['entry_ts']),'side':str(int(src['side'])),'entry_fill':str(src['entry_fill']),
                             'exit_raw':str(src['exit_raw']),'funding':str(src['funding'])})
            delta=float(r['net_per_unit_notional'])-float(orig['net_per_unit_notional']);diffs.append(delta)
            changes.append({'observation_id':r['observation_id'],'leverage':lev,'action':r['time_stop_action'],
                            'baseline_net':float(orig['net_per_unit_notional']),'new_net':float(r['net_per_unit_notional']),'difference':delta})
        row0=next(a for a in baseline_summary['rows'] if a['leverage']==lev and a['exit_slippage_pct']==.05)
        extra_unknown=len(subset)-len(pairs);unknown=row0['unknown_candidates']+extra_unknown
        for cohort,trades in [('baseline_paired',base),('time_stop',new)]:
            for slip in (D('.0005'),D('.00075'),D('.001')):
                out.append({'leverage':lev,'cohort':cohort,'exit_slippage_pct':float(slip*100),**metric(trades,slip),
                            'known_no_order':row0['known_no_order'],'unknown_candidates':unknown})
        out.append({'leverage':lev,'cohort':'pair_changes','paired_paths':len(pairs),
                    'early_exit_paths':sum(r['time_stop_action']=='early_exit' for r in pairs),
                    'better':sum(x>1e-12 for x in diffs),'worse':sum(x< -1e-12 for x in diffs),
                    'unchanged':sum(abs(x)<=1e-12 for x in diffs),'extra_unknown_paths':extra_unknown})
    pd.DataFrame(changes).to_csv(H/'进展退出配对明细.csv',index=False,encoding='utf-8')
    result={'rows':out,'baseline_sha256':bulk.sha(R98/'原始逐笔汇总.json'),'path_audit_sha256':bulk.sha(H/'进展退出独立核验.json'),
            'pair_sha256':bulk.sha(H/'进展退出配对明细.csv'),'frozen_sha256':bulk.sha(H/'研究冻结.json'),
            'code_sha256':bulk.sha(Path(__file__)),'note':'Paired known paths only, unknown candidates and rank hours persist; non-blind research.'}
    (H/'进展退出结果汇总.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT100_SUMMARY',json.dumps(out,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
