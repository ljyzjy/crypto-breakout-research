"""Apply the frozen same-phase count gate to risk-audited raw paths."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys
import pandas as pd
import count_same_phase as engine

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';R102=H.parent/'第一百零二轮_大柱持有损益核查';D=Decimal
sys.path.insert(0,str(R98));from summarize import metric


def main():
    engine.bulk.runner.guard(start=True);engine.frozen()
    proof=json.loads((H/'同秒计数独立核验.json').read_text(encoding='utf-8'));counts=json.loads((H/'同秒计数结果.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['source_sha256']==engine.bulk.sha(H/'同秒计数结果.json')
    assert proof['code_sha256']==engine.bulk.sha(H/'audit_counts.py') and counts['fingerprint']==engine.fingerprint()
    labelproof=json.loads((R102/'大柱标签独立核验.json').read_text(encoding='utf-8'))
    assert labelproof['all_checks_pass'] and labelproof['labels_sha256']==engine.bulk.sha(R102/'事后大柱标签.parquet')
    labels=pd.read_parquet(R102/'事后大柱标签.parquet').set_index('observation_id').to_dict('index')
    count_by={r['observation_id']:r for r in counts['events']}
    base=pd.read_csv(R98/'候选状态与单位账本.csv',dtype=str,keep_default_na=False);assert len(base)==620
    details=[];result=[];groups=[]
    for lev in (10,20):
        group=base[base.leverage==str(lev)].to_dict('records');baseline=[];selected=[];unknown_extra=0;rejected=0
        assert len(group)==310
        for r in group:
            item={**r,'baseline_category':r['category'],'count_status':'','current_n':'','previous_total':'','large_label':''}
            if r['category']=='trade':
                baseline.append(r);c=count_by[r['observation_id']];item.update(count_status=c['status'],current_n=c.get('current_n',''),previous_total=c.get('previous_total',''))
                lab=labels[r['observation_id']];item['large_label']='unknown' if lab['status']!='verified' else 'large_aligned' if bool(lab['large_aligned']) else 'other'
                if c['status']!='verified':item.update(category='unknown',reason='count_'+c['status']);unknown_extra+=1
                elif not c['accepted']:item.update(category='no_order',reason='same_phase_count_rejected');rejected+=1
                else:selected.append(r)
            details.append(item)
        base_unknown=sum(r['category']=='unknown' for r in group)
        for name,trades,unk in [('baseline',baseline,base_unknown),('same_phase_gate',selected,base_unknown+unknown_extra)]:
            for slip in (D('.0005'),D('.00075'),D('.001')):
                result.append({'leverage':lev,'cohort':name,'exit_slippage_pct':float(slip*100),**metric(trades,slip),
                               'known_no_order':310-unk-len(trades),'unknown_candidates':unk})
        for label in ('large_aligned','other','unknown'):
            for category in ('trade','no_order','unknown'):
                subset=[x for x in details if x['leverage']==str(lev) and x['baseline_category']=='trade' and x['large_label']==label and x['category']==category]
                vals=[D(x['net']) for x in subset]
                groups.append({'leverage':lev,'label':label,'gate_category':category,'trades':len(vals),
                               'net_wins':sum(x>0 for x in vals),'mean_net_pct_notional':float(100*sum(vals)/len(vals)) if vals else None})
        assert len(selected)+rejected+unknown_extra==len(baseline)
    fields=['observation_id','leverage','signal_status','baseline_category','category','reason','count_status','current_n','previous_total','large_label','entry_ts','entry_fill','exit_raw','side','funding','net']
    with (H/'同秒过滤逐笔.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(details)
    out={'rows':result,'ex_post_candle_groups':groups,'candidate_count':310,'detail_sha256':engine.bulk.sha(H/'同秒过滤逐笔.csv'),
         'counts_sha256':engine.bulk.sha(H/'同秒计数结果.json'),'count_audit_sha256':engine.bulk.sha(H/'同秒计数独立核验.json'),
         'frozen_sha256':engine.bulk.sha(H/'研究冻结.json'),'code_sha256':engine.bulk.sha(Path(__file__)),
         'note':'Historical raw-tape counts; post-close candle labels are evaluation only; no floating account equity.'}
    (H/'同秒过滤汇总.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT104_SUMMARY',json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
