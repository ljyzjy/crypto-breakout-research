"""Conditional 10x/20x wallets for audited known raw-trade paths."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys
import pandas as pd
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent; B=H/'原始逐笔批次'; R85=H.parent/'第八十五轮_共享资金条件模拟'
sys.path.insert(0,str(R85));from wallet_simulator import simulate


def load_records():
    detail=pd.read_csv(H/'候选状态与单位账本.csv',dtype=str,keep_default_na=False)
    state={(r['observation_id'],int(r['leverage'])):r['category'] for r in detail.to_dict('records')}
    sig=pd.read_parquet(B/'逐笔信号.parquet').set_index('observation_id').to_dict('index')
    ledger=pd.read_parquet(B/'单位净收益与风险.parquet'); records=[]
    for r in ledger.to_dict('records'):
        obs=r['observation_id'];lev=int(r['variant'].rsplit('_',1)[1].rstrip('x'))
        if state[(obs,lev)]!='trade':continue
        s=sig[obs];assert r['status']==r['risk_status']=='verified' and not r['liq_proxy']
        assert s['status']=='qualified' and s[f'precheck_{lev}x']=='passed' and s['entry_exec_ts']==r['entry_signal_reference_ts']
        funding=json.loads(r['funding_events_json']);assert abs(sum(float(x['charge']) for x in funding)-float(r['funding']))<1e-11
        records.append({'period':'original','observation_id':obs,'variant':r['variant'],'leverage':lev,'base':True,
                        'side':int(r['side']),'decision_ts':int(r['decision_ts']),
                        'reference_ts':int(s['entry_exec_ts']),'reference':str(s['raw_entry_1s']),'stop':str(s['stop_price']),
                        'entry_ts':int(r['entry_ts']),'entry_fill':str(r['entry_fill']),'exit_signal_ts':int(r['exit_signal_ts']),
                        'exit_ts':int(r['exit_ts']),'exit_fill':str(r['exit_fill']),'unit_net':str(r['net_per_unit_notional']),
                        'funding_events':funding})
    assert len({(r['observation_id'],r['leverage']) for r in records})==len(records)
    return records


def main():
    bulk.runner.guard(start=True);bulk.frozen()
    audit=json.loads((H/'原始逐笔汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['report_sha256']==bulk.sha(H/'原始逐笔汇总.json') and audit['detail_sha256']==bulk.sha(H/'候选状态与单位账本.csv')
    test=json.loads((R85/'钱包时序合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256']==bulk.sha(R85/'wallet_simulator.py')
    records=load_records();summaries=[];outcomes=[];journals=[]
    for lev in (10,20):
        selected=[r for r in records if r['leverage']==lev]
        for reverse in (False,True):
            summary,rows,journal=simulate(selected,lev,reverse_ties=reverse);extra={'cohort':'base','leverage':lev,'period':'original','reverse_ties':reverse}
            summaries.append({**extra,**{k:float(v) if isinstance(v,Decimal) else v for k,v in summary.items()}})
            for obs,value in rows.items():
                outcomes.append({**extra,'observation_id':obs,'source_period':'original',**{k:value.get(k) for k in ('status','quantity','net_pnl','planned_risk','reference_wallet','estimated_entry','margin','open_fee','funding_paid')}})
            journals.extend({**extra,**j} for j in journal)
    for name,data in [('共享钱包情景逐笔.csv',outcomes),('共享钱包事件账本.csv',journals)]:
        assert data
        with (H/name).open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    out={'rows':summaries,'outcomes_sha256':bulk.sha(H/'共享钱包情景逐笔.csv'),'journal_sha256':bulk.sha(H/'共享钱包事件账本.csv'),
         'frozen_sha256':bulk.sha(H/'研究冻结.json'),'test_sha256':bulk.sha(R85/'钱包时序合成核验.json'),
         'engine_sha256':bulk.sha(R85/'wallet_simulator.py'),'code_sha256':bulk.sha(Path(__file__)),'unknown_rank_hours':240,
         'note':'Known paths only; unresolved candidates skipped, floating equity not tracked.'}
    (H/'共享钱包情景汇总.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT98_WALLET',json.dumps([x for x in summaries if not x['reverse_ties']],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
