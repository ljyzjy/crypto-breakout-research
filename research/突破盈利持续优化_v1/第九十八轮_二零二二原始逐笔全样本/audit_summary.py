"""Reconstruct raw candidate classes and six summary cells independently."""
from collections import Counter
from decimal import Decimal
import json
import math
from pathlib import Path
import pandas as pd
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent;B=H/'原始逐笔批次';D=Decimal


def near(a,b):
    return a is b if a is None or b is None else math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-10)


def main():
    bulk.runner.guard(start=True); report=json.loads((H/'原始逐笔汇总.json').read_text(encoding='utf-8'))
    assert report['code_sha256']==bulk.sha(H/'summarize.py') and report['detail_sha256']==bulk.sha(H/'候选状态与单位账本.csv')
    sig=pd.read_parquet(B/'逐笔信号.parquet').set_index('observation_id').to_dict('index')
    paths=pd.read_parquet(B/'模拟路径.parquet').set_index(['observation_id','variant']).to_dict('index')
    ledger=pd.read_parquet(B/'单位净收益与风险.parquet').set_index(['observation_id','variant']).to_dict('index')
    detail=pd.read_csv(H/'候选状态与单位账本.csv',dtype=str,keep_default_na=False)
    assert len(detail)==620 and not detail.duplicated(['observation_id','leverage']).any()
    valid={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    checked=0
    for lev,g in detail.groupby('leverage'):
        assert len(g)==len(sig);counts=Counter();series={k:[] for k in ('0.05','0.075','0.1')};days=set()
        for x in g.to_dict('records'):
            s=sig[x['observation_id']];key=(x['observation_id'],'one_observation_2r_'+lev+'x');p=paths.get(key);r=ledger.get(key)
            status=s['status'];pre=s['precheck_'+lev+'x']
            if status not in valid: category='unknown'
            elif status!='qualified': category='no_order'
            elif pd.isna(pre):category='unknown'
            elif pre!='passed':category='no_order'
            elif p is None or p['status']!='verified':category='unknown'
            elif r is None or r['risk_status']!='verified' or bool(r['liq_proxy']):category='unknown'
            else:category='trade'
            assert category==x['category'],(x['observation_id'],lev,category,x['category']);counts[category]+=1
            if category=='trade':
                side=int(r['side']);entry=D(str(r['entry_fill']));raw=D(str(r['exit_raw']));fund=D(str(r['funding']))
                assert int(x['entry_ts'])==int(r['entry_ts']) and int(x['side'])==side
                assert int(r['entry_ts'])>=int(r['decision_ts'])+2000 and int(r['exit_ts'])>=int(r['exit_signal_ts'])+5000
                days.add(pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d'))
                for slip in series:
                    ex=raw*(1-D(side)*D(slip)/100); net=D(side)*(ex-entry)/entry-D('.0005')-D('.0005')*ex/entry-fund
                    if slip=='0.05':assert abs(net-D(x['net']))<D('1e-11')
                    series[slip].append(net)
            checked+=1
        for row in [a for a in report['rows'] if str(a['leverage'])==lev]:
            vals=series[str(row['exit_slippage_pct'])];wins=[v for v in vals if v>0];losses=[v for v in vals if v<0]
            assert row['trades']==counts['trade']==len(vals) and row['known_no_order']==counts['no_order'] and row['unknown_candidates']==counts['unknown']
            assert row['net_wins']==len(wins) and row['active_utc_days']==len(days)
            assert near(row['net_win_rate_pct'],100*len(wins)/len(vals) if vals else None)
            assert near(row['mean_net_pct_notional'],100*sum(vals)/len(vals) if vals else None)
            assert near(row['profit_factor'],sum(wins)/-sum(losses) if losses else None)
    previous=pd.read_csv(bulk.R90/'二零二二候选状态及单位账本.csv',dtype=str,keep_default_na=False)
    affected=set(json.loads((H.parent/'第九十三轮_原始逐笔抽样交叉核验/原始数据分歧敏感性.json').read_text(encoding='utf-8'))['affected_observation_ids'])
    for row in report['paired_categories']:
        lev=str(row['leverage']); earlier=previous[(previous.holding_rule=='original')&(previous.leverage==lev)&(previous.cohort=='base')]
        first={r['observation_id']:('unknown' if r['observation_id'] in affected else r['category']) for r in earlier.to_dict('records')}
        later={r['observation_id']:r['category'] for r in detail[detail.leverage==lev].to_dict('records')}
        assert len(first)==len(later)==310 and set(first)==set(later)
        observed=Counter((first[k],later[k]) for k in first)
        stated={(a['category_agg'],a['category_raw']):a['n'] for a in row['categories']}
        assert dict(observed)==stated and row['common_trades']==observed[('trade','trade')]
    out={'all_checks_pass':True,'candidate_classifications_checked':checked,'summary_groups_checked':len(report['rows']),
         'paired_category_groups_checked':len(report['paired_categories']),
         'report_sha256':bulk.sha(H/'原始逐笔汇总.json'),'detail_sha256':bulk.sha(H/'候选状态与单位账本.csv'),
         'code_sha256':bulk.sha(Path(__file__)),'note':'Independent classification and unit arithmetic; no account equity.'}
    (H/'原始逐笔汇总独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT98_SUMMARY_AUDIT',checked,len(report['rows']),flush=True)


if __name__=='__main__':main()
