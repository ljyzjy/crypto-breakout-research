"""Apply the frozen time-stop to risk-verified raw paths and resettle funding."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pandas as pd

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';B=R98/'原始逐笔批次'
sys.path.insert(0,str(R98));import run_raw_2022 as bulk
sys.path.insert(0,str(bulk.R90));import settle_risk_2022 as risk
sys.path.insert(0,str(bulk.R93));import compare_raw_aggregate as raw
from time_stop import apply


def frozen():
    f=json.loads((H/'研究冻结.json').read_text(encoding='utf-8'))
    for path,digest in f['sources'].items():assert bulk.sha(path)==digest,path
    assert f['raw_batch_fingerprint']==bulk.fingerprint() and f['check_delay_ms']==30000 and f['minimum_progress_in_r']==.25
    test=json.loads((H/'进展退出合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==bulk.sha(H/'time_stop.py') and test['test_sha256']==bulk.sha(H/'test_time_stop.py')
    return f


def risk_inputs():
    proof=json.loads((R98/'风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    source=json.loads((B/'风险来源与结算.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['input_sha256']==bulk.sha(B/'风险来源与结算.json') and proof['ledger_sha256']==bulk.sha(B/'单位净收益与风险.parquet')
    marks={};funds={};statuses={}
    for info in source['sources']:
        key=(info['kind'],info['contract'],info['month']);statuses[key]=info['status']
        if info['status']!='verified':continue
        path=Path(info['cache_path']);assert bulk.sha(path)==info['cache_sha256']
        cache=json.loads(path.read_text(encoding='utf-8'));assert cache['status']=='verified' and cache['sha256']==info['sha256']
        if info['kind']=='markPriceKlines':
            for r in cache['rows']:marks[(info['contract'],int(r['ts']))]=r
        else:funds[(info['contract'],info['month'])]=cache['rows']
    return marks,funds,statuses


def main():
    bulk.runner.guard(start=True);frozen()
    proof=json.loads((R98/'原始逐笔汇总独立核验.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['report_sha256']==bulk.sha(R98/'原始逐笔汇总.json')
    detail=pd.read_csv(R98/'候选状态与单位账本.csv',dtype=str,keep_default_na=False)
    eligible={(r['observation_id'],int(r['leverage'])) for r in detail.to_dict('records') if r['category']=='trade'}
    ledger=pd.read_parquet(B/'单位净收益与风险.parquet');candidates=pd.read_parquet(bulk.R90/'候选数据/固定十一币双币过滤潜在触价.parquet')
    grouped={}
    for r in ledger.to_dict('records'):
        lev=int(r['variant'].rsplit('_',1)[1].rstrip('x'));key=(r['observation_id'],lev)
        if key in eligible:grouped.setdefault(key[0],[]).append(r)
    assert sum(map(len,grouped.values()))==len(eligible)
    marks,funds,statuses=risk_inputs();env,_=risk.risk_namespace();outputs=[];case_log=[]
    for (sym,day),group in candidates.groupby(['contract','day'],sort=True):
        if not set(group.observation_id).intersection(grouped):continue
        bulk.runner.guard();events=group.to_dict('records');cp_path=bulk.runner.ROOT/'raw_2022_full_checkpoints'/(bulk.runner.key(bulk.fingerprint(),sym,day,events)+'.json')
        cp=json.loads(cp_path.read_text(encoding='utf-8'));assert cp['fingerprint']==bulk.fingerprint()
        arcs=[a for a in cp['archives'] if a['kind']=='trades']
        need=any(int(r['exit_signal_ts'])>int(r['entry_ts'])+30000 for e in events for r in grouped.get(e['observation_id'],[]))
        if need:
            for a in arcs:assert bulk.sha(a['path'])==a['sha256']
        for e in events:
            obs=e['observation_id'];paths=grouped.get(obs,[])
            if not paths:continue
            to_check=[r for r in paths if int(r['exit_signal_ts'])>int(r['entry_ts'])+30000]
            prices=[]
            if to_check:
                lo=min(int(r['entry_ts']) for r in to_check);hi=max(int(r['exit_ts']) for r in to_check)+1;source=[]
                for a in arcs:source.extend(raw.read_window(a['path'],'trades',lo,hi))
                source.sort(key=lambda r:(r[0],r[1]));prices=[(r[0],float(r[2])) for r in source]
            for r in paths:
                action=apply(r,prices);new=dict(r)
                if action['action']=='early_exit':
                    for k in ('exit_signal_ts','exit_ts','exit_raw','exit_fill'):new[k]=action[k]
                    new['reason']='insufficient_30s_progress'
                    settled=env['settle'](SimpleNamespace(**new),marks,funds,statuses);new.update(settled)
                elif action['action']=='unknown':
                    new.update(risk_status='time_stop_unknown',liq_proxy=None,funding=None,funding_events_json=None,
                               entry_fee=None,exit_fee=None,net_per_unit_notional=None,net_pct_notional=None)
                new['baseline_net_per_unit_notional']=r['net_per_unit_notional'];new['baseline_exit_ts']=r['exit_ts']
                new['time_stop_action']=action['action'];new['time_stop_reason']=action['reason']
                new['check_ts']=action.get('check_ts');new['progress_r']=action.get('progress_r')
                outputs.append(new);case_log.append({'observation_id':obs,'variant':r['variant'],**action})
            print('EXT100_CASE',len(case_log),'/',len(eligible),sym,day,flush=True)
    assert len(outputs)==len(eligible) and len(case_log)==len(eligible)
    out=pd.DataFrame(outputs);assert not out.duplicated(['observation_id','variant']).any()
    out.to_parquet(H/'进展退出单位账本.parquet',index=False)
    info={'candidate_paths':len(out),'actions':out.time_stop_action.value_counts().to_dict(),
          'risk_statuses':out.risk_status.value_counts().to_dict(),'cases':case_log,
          'ledger_sha256':bulk.sha(H/'进展退出单位账本.parquet'),'baseline_audit_sha256':bulk.sha(R98/'原始逐笔汇总独立核验.json'),
          'risk_audit_sha256':bulk.sha(R98/'风险来源与账本独立核验.json'),'frozen_sha256':bulk.sha(H/'研究冻结.json'),
          'engine_sha256':bulk.sha(H/'time_stop.py'),'code_sha256':bulk.sha(Path(__file__)),
          'note':'Earlier exits settled against previously independently audited raw risk caches; new path still needs independent replay.'}
    (H/'进展退出回放质量.json').write_text(json.dumps(info,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('EXT100_FINISHED',len(out),info['actions'],flush=True)


if __name__=='__main__':main()
