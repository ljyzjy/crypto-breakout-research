"""Compare same-path known wallets with and without the progress exit."""
import csv
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';R85=H.parent/'第八十五轮_共享资金条件模拟'
sys.path.insert(0,str(R98));spec=importlib.util.spec_from_file_location('ext98_wallet',R98/'run_wallet.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);bulk=base.bulk


def load_records():
    new=pd.read_parquet(H/'进展退出单位账本.parquet').set_index(['observation_id','variant']).to_dict('index');out=[]
    for old in base.load_records():
        r=new[(old['observation_id'],old['variant'])]
        if r['risk_status']!='verified' or bool(r['liq_proxy']):continue
        out.append({**old,'period':'baseline_paired'})
        out.append({**old,'period':'time_stop','exit_signal_ts':int(r['exit_signal_ts']),'exit_ts':int(r['exit_ts']),
                    'exit_fill':str(r['exit_fill']),'unit_net':str(r['net_per_unit_notional']),'funding_events':json.loads(r['funding_events_json'])})
    return out


def main():
    bulk.runner.guard(start=True);audit=json.loads((H/'进展退出汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256']==bulk.sha(H/'进展退出结果汇总.json')
    prev=json.loads((R98/'共享钱包独立核验.json').read_text(encoding='utf-8'))
    assert prev['all_checks_pass'] and prev['result_sha256']==bulk.sha(R98/'共享钱包情景汇总.json')
    records=load_records();summaries=[];outcomes=[];journals=[]
    for lev in (10,20):
      for period in ('baseline_paired','time_stop'):
       selected=[r for r in records if r['leverage']==lev and r['period']==period]
       for reverse in (False,True):
        summary,rows,journal=base.simulate(selected,lev,reverse_ties=reverse);extra={'cohort':'base','leverage':lev,'period':period,'reverse_ties':reverse}
        summaries.append({**extra,**{k:float(v) if isinstance(v,Decimal) else v for k,v in summary.items()}})
        for obs,value in rows.items():outcomes.append({**extra,'observation_id':obs,'source_period':period,**{k:value.get(k) for k in ('status','quantity','net_pnl','planned_risk','reference_wallet','estimated_entry','margin','open_fee','funding_paid')}})
        journals.extend({**extra,**j} for j in journal)
    for name,data in [('共享钱包情景逐笔.csv',outcomes),('共享钱包事件账本.csv',journals)]:
        default=(['cohort','leverage','period','reverse_ties','observation_id','source_period','status','quantity','net_pnl','planned_risk','reference_wallet','estimated_entry','margin','open_fee','funding_paid']
                 if name=='共享钱包情景逐笔.csv' else ['cohort','leverage','period','reverse_ties','ts','event','observation_id','status','wallet','locked_margin','pending_reserve','planned_open_risk'])
        with (H/name).open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]) if data else default);w.writeheader();w.writerows(data)
    result={'rows':summaries,'outcomes_sha256':bulk.sha(H/'共享钱包情景逐笔.csv'),'journal_sha256':bulk.sha(H/'共享钱包事件账本.csv'),
            'frozen_sha256':bulk.sha(H/'研究冻结.json'),'test_sha256':bulk.sha(R85/'钱包时序合成核验.json'),
            'engine_sha256':bulk.sha(R85/'wallet_simulator.py'),'code_sha256':bulk.sha(Path(__file__)),'unknown_rank_hours':240,
            'note':'Known paired paths only; original unknowns and floating equity excluded.'}
    (H/'共享钱包情景汇总.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT100_WALLET',json.dumps([x for x in summaries if not x['reverse_ties']],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
