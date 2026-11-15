"""Run the known-path wallet with the fixed same-phase trade-count gate."""
import csv
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';R85=H.parent/'第八十五轮_共享资金条件模拟';D=Decimal
sys.path.insert(0,str(R98));spec=importlib.util.spec_from_file_location('ext98_baseline_wallet',R98/'run_wallet.py')
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline);bulk=baseline.bulk


def load_records():
    counts=json.loads((H/'同秒计数结果.json').read_text(encoding='utf-8'))['events']
    accepted={x['observation_id'] for x in counts if x['status']=='verified' and x['accepted']}
    return [r for r in baseline.load_records() if r['observation_id'] in accepted]


def main():
    baseline.bulk.runner.guard(start=True);audit=json.loads((H/'同秒过滤独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256']==baseline.bulk.sha(H/'同秒过滤汇总.json')
    test=json.loads((H/'严格秒窗合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==baseline.bulk.sha(H/'count_same_phase.py')
    assert test['test_sha256']==baseline.bulk.sha(H/'test_windows.py')
    prior=json.loads((R98/'共享钱包独立核验.json').read_text(encoding='utf-8'))
    assert prior['all_checks_pass'] and prior['result_sha256']==baseline.bulk.sha(R98/'共享钱包情景汇总.json')
    records=load_records();summaries=[];outcomes=[];journals=[]
    for lev in (10,20):
        selected=[r for r in records if r['leverage']==lev]
        for reverse in (False,True):
            summary,rows,journal=baseline.simulate(selected,lev,reverse_ties=reverse);extra={'cohort':'base','leverage':lev,'period':'original','reverse_ties':reverse}
            summaries.append({**extra,**{k:float(v) if isinstance(v,Decimal) else v for k,v in summary.items()}})
            for obs,value in rows.items():outcomes.append({**extra,'observation_id':obs,'source_period':'original',**{k:value.get(k) for k in ('status','quantity','net_pnl','planned_risk','reference_wallet','estimated_entry','margin','open_fee','funding_paid')}})
            journals.extend({**extra,**j} for j in journal)
    for name,data in [('共享钱包情景逐笔.csv',outcomes),('共享钱包事件账本.csv',journals)]:
        default_columns=(['cohort','leverage','period','reverse_ties','observation_id','source_period','status','quantity','net_pnl','planned_risk','reference_wallet','estimated_entry','margin','open_fee','funding_paid']
                         if name=='共享钱包情景逐笔.csv' else ['cohort','leverage','period','reverse_ties','ts','event','observation_id','status','wallet','locked_margin','pending_reserve','planned_open_risk'])
        with (H/name).open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]) if data else default_columns);w.writeheader();w.writerows(data)
    out={'rows':summaries,'outcomes_sha256':baseline.bulk.sha(H/'共享钱包情景逐笔.csv'),'journal_sha256':baseline.bulk.sha(H/'共享钱包事件账本.csv'),
         'frozen_sha256':baseline.bulk.sha(H/'研究冻结.json'),'test_sha256':baseline.bulk.sha(R85/'钱包时序合成核验.json'),
         'engine_sha256':baseline.bulk.sha(R85/'wallet_simulator.py'),'code_sha256':baseline.bulk.sha(Path(__file__)),
         'unknown_rank_hours':240,'note':'Conditional known paths only. Unknown opportunities and floating equity remain excluded.'}
    (H/'共享钱包情景汇总.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT104_WALLET',json.dumps([x for x in summaries if not x['reverse_ties']],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
