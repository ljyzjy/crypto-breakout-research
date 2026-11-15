"""Independently recompute paired progress-exit metrics and categories."""
from decimal import Decimal
import json
import math
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本';B=R98/'原始逐笔批次';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def near(a,b):return a is b if a is None or b is None else math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)


def main():
    bulk.runner.guard(start=True);report=json.loads((H/'进展退出结果汇总.json').read_text(encoding='utf-8'))
    assert report['code_sha256']==bulk.sha(H/'summarize.py') and report['pair_sha256']==bulk.sha(H/'进展退出配对明细.csv')
    original=pd.read_parquet(B/'单位净收益与风险.parquet').set_index(['observation_id','variant']).to_dict('index')
    current=pd.read_parquet(H/'进展退出单位账本.parquet').to_dict('records')
    detail=pd.read_csv(H/'进展退出配对明细.csv');base=json.loads((R98/'原始逐笔汇总.json').read_text(encoding='utf-8'))
    checked=0
    for lev in (10,20):
        variant=f'one_observation_2r_{lev}x';subset=[r for r in current if r['variant']==variant]
        pairs=[r for r in subset if r['risk_status']=='verified' and not bool(r['liq_proxy'])]
        pair_detail=detail[detail.leverage==lev].set_index('observation_id').to_dict('index')
        assert len(pair_detail)==len(pairs);values={(c,s):[] for c in ('baseline_paired','time_stop') for s in ('0.05','0.075','0.1')};days=set();diff=[]
        for r in pairs:
            obs=r['observation_id'];orig=original[(obs,variant)];saved=pair_detail[obs]
            delta=float(r['net_per_unit_notional'])-float(orig['net_per_unit_notional']);diff.append(delta)
            assert near(saved['baseline_net'],orig['net_per_unit_notional']) and near(saved['new_net'],r['net_per_unit_notional']) and near(saved['difference'],delta)
            assert saved['action']==r['time_stop_action'];days.add(pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d'))
            for cohort,rec in [('baseline_paired',orig),('time_stop',r)]:
                side=int(rec['side']);entry=D(str(rec['entry_fill']));raw=D(str(rec['exit_raw']));fund=D(str(rec['funding']))
                for slip in ('0.05','0.075','0.1'):
                    exit=raw*(1-D(side)*D(slip)/100);net=D(side)*(exit-entry)/entry-D('.0005')-D('.0005')*exit/entry-fund
                    values[(cohort,slip)].append(net)
            checked+=1
        base_row=next(x for x in base['rows'] if x['leverage']==lev and x['exit_slippage_pct']==.05)
        for row in [x for x in report['rows'] if x['leverage']==lev and x['cohort']!='pair_changes']:
            vals=values[(row['cohort'],str(row['exit_slippage_pct']))];wins=[v for v in vals if v>0];losses=[v for v in vals if v<0]
            assert row['trades']==len(vals)==len(pairs) and row['net_wins']==len(wins) and row['active_utc_days']==len(days)
            assert row['known_no_order']==base_row['known_no_order'] and row['unknown_candidates']==base_row['unknown_candidates']+len(subset)-len(pairs)
            assert near(row['net_win_rate_pct'],100*len(wins)/len(vals) if vals else None)
            assert near(row['mean_net_pct_notional'],100*sum(vals)/len(vals) if vals else None)
            assert near(row['profit_factor'],sum(wins)/-sum(losses) if losses else None)
        change=next(x for x in report['rows'] if x['leverage']==lev and x['cohort']=='pair_changes')
        assert change['paired_paths']==len(pairs) and change['early_exit_paths']==sum(r['time_stop_action']=='early_exit' for r in pairs)
        assert change['better']==sum(x>1e-12 for x in diff) and change['worse']==sum(x< -1e-12 for x in diff) and change['unchanged']==sum(abs(x)<=1e-12 for x in diff)
    out={'all_checks_pass':True,'paired_paths_checked':checked,'result_sha256':bulk.sha(H/'进展退出结果汇总.json'),
         'detail_sha256':bulk.sha(H/'进展退出配对明细.csv'),'code_sha256':bulk.sha(Path(__file__)),
         'note':'Independently recalculated each paired score and status; no true fills or account equity.'}
    (H/'进展退出汇总独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT100_SUMMARY_AUDIT',checked,flush=True)


if __name__=='__main__':main()
