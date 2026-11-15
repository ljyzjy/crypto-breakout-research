"""Apply the frozen cost-to-target gate to audited known raw 2022 paths."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';B=R98/'原始逐笔批次';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk
from summarize import metric


def check_frozen():
    f=json.loads((H/'研究冻结.json').read_text(encoding='utf-8'))
    for path,digest in f['sources'].items():assert bulk.sha(path)==digest,path
    assert f['raw_batch_fingerprint']==bulk.fingerprint() and f['minimum_directional_stop_fraction']==.004


def main():
    bulk.runner.guard(start=True);check_frozen()
    audit=json.loads((R98/'原始逐笔汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['report_sha256']==bulk.sha(R98/'原始逐笔汇总.json')
    original=pd.read_csv(R98/'候选状态与单位账本.csv',dtype=str,keep_default_na=False)
    signals=pd.read_parquet(B/'逐笔信号.parquet').set_index('observation_id').to_dict('index')
    assert len(original)==620 and len(signals)==310
    details=[];rows=[]
    for lev in (10,20):
        base=original[original.leverage==str(lev)].to_dict('records');assert len(base)==310
        trades=[];before=[]
        for r in base:
            s=signals[r['observation_id']];item={**r,'baseline_category':r['category'],'gate_fraction':''}
            if r['category']=='trade':
                p=D(str(s['raw_entry_1s']));stop=D(str(s['stop_price']));side=int(s['side'])
                assert p>0 and side in (-1,1) and int(s['entry_exec_ts'])>=int(s['decision_ts'])+1000
                fraction=D(side)*(p-stop)/p;item['gate_fraction']=str(fraction);before.append(r)
                if fraction<D('.004'):item.update(category='no_order',reason='cost_target_gate_rejected')
                else:trades.append(r)
            details.append(item)
        unknown=sum(r['category']=='unknown' for r in base); no_order=310-unknown-len(trades)
        for label,group in [('baseline',before),('cost_target_gate',trades)]:
            for slip in (D('.0005'),D('.00075'),D('.001')):
                rows.append({'leverage':lev,'cohort':label,'exit_slippage_pct':float(slip*100),**metric(group,slip),
                             'known_no_order':310-unknown-len(group),'unknown_candidates':unknown})
        assert no_order>=0
    columns=['observation_id','leverage','signal_status','baseline_category','category','reason','gate_fraction','entry_ts','entry_fill','exit_raw','side','funding','net']
    with (H/'过滤候选账本.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(details)
    out={'rows':rows,'candidate_count':310,'code_sha256':bulk.sha(Path(__file__)),'frozen_sha256':bulk.sha(H/'研究冻结.json'),
         'detail_sha256':bulk.sha(H/'过滤候选账本.csv'),'baseline_sha256':bulk.sha(R98/'原始逐笔汇总.json'),
         'baseline_audit_sha256':bulk.sha(R98/'原始逐笔汇总独立核验.json'),
         'note':'Known trades filtered using observation-time inputs; original unknowns conservatively retained; retrospective, not account equity.'}
    (H/'成本波幅过滤汇总.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT99_SUMMARY',json.dumps(rows,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
