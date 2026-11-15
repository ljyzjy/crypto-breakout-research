"""Recompute count gate classifications, cost stresses and post-hoc label groups."""
from collections import Counter
from decimal import Decimal
import json
import math
from pathlib import Path
import pandas as pd
import count_same_phase as engine

H=Path(__file__).resolve().parent;P=H.parent;R98=P/'第九十八轮_二零二二原始逐笔全样本';R102=P/'第一百零二轮_大柱持有损益核查';D=Decimal


def near(a,b):return a is b if a is None or b is None else math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)


def main():
    engine.bulk.runner.guard(start=True);report=json.loads((H/'同秒过滤汇总.json').read_text(encoding='utf-8'))
    assert report['code_sha256']==engine.bulk.sha(H/'summarize.py') and report['detail_sha256']==engine.bulk.sha(H/'同秒过滤逐笔.csv')
    counts={r['observation_id']:r for r in json.loads((H/'同秒计数结果.json').read_text(encoding='utf-8'))['events']}
    signals=pd.read_parquet(R98/'原始逐笔批次/逐笔信号.parquet').set_index('observation_id').to_dict('index')
    labels=pd.read_parquet(R102/'事后大柱标签.parquet').set_index('observation_id').to_dict('index')
    old=pd.read_csv(R98/'候选状态与单位账本.csv',dtype=str,keep_default_na=False).set_index(['observation_id','leverage']).to_dict('index')
    detail=pd.read_csv(H/'同秒过滤逐笔.csv',dtype=str,keep_default_na=False);assert len(detail)==len(old)==620
    group_check={};checked=0
    for lev,g in detail.groupby('leverage'):
        stats={c:Counter() for c in ('baseline','same_phase_gate')};values={(c,s):[] for c in stats for s in ('0.05','0.075','0.1')};days={c:set() for c in stats}
        for x in g.to_dict('records'):
            obs=x['observation_id'];r=old[(obs,lev)];category=r['category'];assert x['baseline_category']==category
            if category=='trade':
                c=counts[obs];s=signals[obs];assert int(c['decision_ts'])==int(s['decision_ts'])
                if c['status']=='verified':
                    assert c['current_n']==int(s['one_count']) and c['previous_total']==sum(c['previous_counts']) and c['previous_total']>0
                    accepted=40*c['current_n']>=3*c['previous_total'];assert c['accepted']==accepted
                    new='trade' if accepted else 'no_order'
                else:new='unknown'
                lab=labels[obs];label='unknown' if lab['status']!='verified' else 'large_aligned' if bool(lab['large_aligned']) else 'other'
                assert x['large_label']==label and x['count_status']==c['status']
                group_check.setdefault((int(lev),label,new),[]).append(D(r['net']))
            else:new=category
            assert x['category']==new
            for cohort,cat in [('baseline',category),('same_phase_gate',new)]:
                stats[cohort][cat]+=1
                if cat!='trade':continue
                side=D(r['side']);entry=D(r['entry_fill']);raw=D(r['exit_raw']);fund=D(r['funding'])
                days[cohort].add(pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d'))
                for slip in ('0.05','0.075','0.1'):
                    ex=raw*(1-side*D(slip)/100);net=side*(ex-entry)/entry-D('.0005')-D('.0005')*ex/entry-fund
                    values[(cohort,slip)].append(net)
            checked+=1
        for row in [r for r in report['rows'] if str(r['leverage'])==lev]:
            cohort=row['cohort'];vals=values[(cohort,str(row['exit_slippage_pct']))];win=[v for v in vals if v>0];loss=[v for v in vals if v<0]
            assert row['trades']==len(vals)==stats[cohort]['trade'] and row['known_no_order']==stats[cohort]['no_order'] and row['unknown_candidates']==stats[cohort]['unknown']
            assert row['net_wins']==len(win) and row['active_utc_days']==len(days[cohort])
            assert near(row['net_win_rate_pct'],100*len(win)/len(vals) if vals else None)
            assert near(row['mean_net_pct_notional'],100*sum(vals)/len(vals) if vals else None)
            assert near(row['profit_factor'],sum(win)/-sum(loss) if loss else None)
    for row in report['ex_post_candle_groups']:
        vals=group_check.get((row['leverage'],row['label'],row['gate_category']),[])
        assert row['trades']==len(vals) and row['net_wins']==sum(v>0 for v in vals)
        assert near(row['mean_net_pct_notional'],100*sum(vals)/len(vals) if vals else None)
    out={'all_checks_pass':True,'candidate_classifications_checked':checked,'summary_groups_checked':len(report['rows']),
         'candle_groups_checked':len(report['ex_post_candle_groups']),'result_sha256':engine.bulk.sha(H/'同秒过滤汇总.json'),
         'detail_sha256':engine.bulk.sha(H/'同秒过滤逐笔.csv'),'code_sha256':engine.bulk.sha(Path(__file__)),
         'note':'Classifications and unit arithmetic rebuilt; independent timestamp sample is recorded separately.'}
    (H/'同秒过滤独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT104_SUMMARY_AUDIT',checked,flush=True)


if __name__=='__main__':main()
