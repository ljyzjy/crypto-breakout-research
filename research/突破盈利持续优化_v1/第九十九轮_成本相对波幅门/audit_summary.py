"""Independently reconstruct the frozen signal-time gate and cost statistics."""
from collections import Counter
from decimal import Decimal
import json
import math
from pathlib import Path
import sys
import pandas as pd

H=Path(__file__).resolve().parent;R98=H.parent/'第九十八轮_二零二二原始逐笔全样本'; B=R98/'原始逐笔批次';D=Decimal
sys.path.insert(0,str(R98));import run_raw_2022 as bulk


def near(a,b):return a is b if a is None or b is None else math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)


def main():
    bulk.runner.guard(start=True);report=json.loads((H/'成本波幅过滤汇总.json').read_text(encoding='utf-8'))
    assert report['code_sha256']==bulk.sha(H/'summarize.py') and report['detail_sha256']==bulk.sha(H/'过滤候选账本.csv')
    detail=pd.read_csv(H/'过滤候选账本.csv',dtype=str,keep_default_na=False)
    baseline=pd.read_csv(R98/'候选状态与单位账本.csv',dtype=str,keep_default_na=False).set_index(['observation_id','leverage']).to_dict('index')
    sig=pd.read_parquet(B/'逐笔信号.parquet').set_index('observation_id').to_dict('index')
    ledger=pd.read_parquet(B/'单位净收益与风险.parquet').set_index(['observation_id','variant']).to_dict('index')
    assert len(detail)==len(baseline)==620 and len(sig)==310
    checked=0
    for lev,g in detail.groupby('leverage'):
        counters={k:Counter() for k in ('baseline','cost_target_gate')}
        values={(cohort,slip):[] for cohort in counters for slip in ('0.05','0.075','0.1')};days={k:set() for k in counters}
        for x in g.to_dict('records'):
            obs=x['observation_id'];old=baseline[(obs,lev)];s=sig[obs];assert x['baseline_category']==old['category']
            category=old['category']
            if category=='trade':
                p=D(str(s['raw_entry_1s']));stop=D(str(s['stop_price']));side=int(s['side']);fraction=D(side)*(p-stop)/p
                assert abs(D(x['gate_fraction'])-fraction)<D('1e-15')
                if fraction<D('.004'):category='no_order'
            assert x['category']==category
            for cohort,c in [('baseline',old['category']),('cost_target_gate',category)]:
                counters[cohort][c]+=1
                if c!='trade':continue
                r=ledger[(obs,'one_observation_2r_'+lev+'x')];side=int(r['side']);entry=D(str(r['entry_fill']));raw=D(str(r['exit_raw']));fund=D(str(r['funding']))
                assert int(s['entry_exec_ts'])>=int(s['decision_ts'])+1000 and int(r['entry_ts'])>=int(s['entry_exec_ts'])+1000
                days[cohort].add(pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d'))
                for slip in ('0.05','0.075','0.1'):
                    ex=raw*(1-D(side)*D(slip)/100);n=D(side)*(ex-entry)/entry-D('.0005')-D('.0005')*ex/entry-fund
                    values[(cohort,slip)].append(n)
            checked+=1
        for row in [r for r in report['rows'] if str(r['leverage'])==lev]:
            cohort=row['cohort'];vals=values[(cohort,str(row['exit_slippage_pct']))];wins=[v for v in vals if v>0];losses=[v for v in vals if v<0]
            assert row['trades']==len(vals)==counters[cohort]['trade'] and row['known_no_order']==counters[cohort]['no_order']
            assert row['unknown_candidates']==counters[cohort]['unknown'] and row['net_wins']==len(wins) and row['active_utc_days']==len(days[cohort])
            assert near(row['net_win_rate_pct'],100*len(wins)/len(vals) if vals else None)
            assert near(row['mean_net_pct_notional'],100*sum(vals)/len(vals) if vals else None)
            assert near(row['profit_factor'],sum(wins)/-sum(losses) if losses else None)
    out={'all_checks_pass':True,'candidate_classifications_checked':checked,'summary_groups_checked':len(report['rows']),
         'result_sha256':bulk.sha(H/'成本波幅过滤汇总.json'),'detail_sha256':bulk.sha(H/'过滤候选账本.csv'),
         'code_sha256':bulk.sha(Path(__file__)),'note':'Gate uses pre-entry reference and stop; original unknown candidates remain unknown.'}
    (H/'过滤结果独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT99_AUDIT',checked,len(report['rows']),flush=True)


if __name__=='__main__':main()
