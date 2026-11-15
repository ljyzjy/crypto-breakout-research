"""Tighten unknown counts only when strict source checks prove no order."""
import hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;P=HERE.parent;ROOT=P.parent.parent;ORIG=P/'第三十三轮_动态池逐笔执行'
sys.path.insert(0,str(ORIG))
from leveraged_paths import known_precheck
RAW=ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation';TRAIN=HERE/'训练期分批'
SOURCE=P/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet'

def main():
    sig=pd.read_parquet(TRAIN/'动态池逐笔信号筛查.parquet');s={r['observation_id']:r for r in sig.to_dict('records')}
    candidate=pd.read_parquet(SOURCE).set_index('observation_id');diag=json.loads((TRAIN/'不完整数据下单位机会诊断.json').read_text(encoding='utf-8'))
    assert not diag['whole_screen_complete']
    first_unknown={x['observation_id'] for x in s.values() if x['status']=='upstream_data_unknown'}
    assert len(first_unknown)==sum(~sig.status.isin(['first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified','no_follow_known']))
    fp=hashlib.sha256((ORIG/'reconcile_completed_checkpoints.py').read_bytes()+(ORIG/'raw_reconciliation.py').read_bytes()+
                      (ORIG/'原始成交差异复核规则.json').read_bytes()+SOURCE.read_bytes()).hexdigest()
    noorder={'flow_filter_not_met','known_risk_rejected','first_direction_ineligible','no_order_time'};resolved={}
    for p in sorted(RAW.glob('*.json')):
        rec=json.loads(p.read_text(encoding='utf-8'))
        if rec.get('status')!='verified':continue
        key=fp+'|'+rec['contract']+'|'+rec['day']+'|'+str(rec['needs_next'])+'|'+'|'.join(sorted(x['observation_id'] for x in rec['rows']))
        assert p.stem==hashlib.sha256(key.encode()).hexdigest()
        for x in rec['rows']:
            obs=x['observation_id'];o=x.get('outcome',{});status=o.get('status')
            if obs not in first_unknown or not x.get('reconciled') or status not in noorder:continue
            assert x['raw_matches_kline'] and x['aggregate_open_only'] and not x['paths_checked']
            assert np.allclose(x['aggregate_flow'],x['raw_flow'],rtol=1e-9,atol=1e-8)
            if status=='flow_filter_not_met':
                failed=(o['five_count']<3 or o['five_imbalance'] is None or o['five_imbalance']<.10 or
                        o['side']*(o['raw_entry_5s']-o['level'])<=0)
                assert failed and x['first_cross'][0]==o['decision_ts'] and x['five_second_reference'][0]==o['entry_exec_ts']
            elif status=='known_risk_rejected':
                e=candidate.loc[obs].to_dict();event={**e,**o}
                assert all(known_precheck(event,L) is not None for L in (10,20))
            resolved[obs]={'observation_id':obs,'no_order_status':status,'checkpoint_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                           'contract':rec['contract'],'day':rec['day'],'archives':rec['archives'],'strict_reconciliation':x}
    rows=[]
    for z in diag['rows']:
        if z['period']!='2024_jan_apr':continue
        assert z['possible_unknown_events']==len(first_unknown)
        n=z['verified_subset_events'];wins=z['verified_subset_wins'];unknown=len(first_unknown)-len(resolved)
        rows.append({'variant':z['variant'],'verified_events_unchanged':n,'verified_wins_unchanged':wins,
                     'known_no_order_reconciled':len(resolved),'remaining_unknown_events':unknown,
                     'optimistic_unit_win_rate_upper_pct':100*(wins+unknown)/(n+unknown) if n+unknown else None})
    out={'training_initial_unknown':len(first_unknown),'strict_no_order_reconciled':len(resolved),
         'remaining_unknown':len(first_unknown)-len(resolved),'rows':rows,'resolved_source_records':list(resolved.values()),
         'rule_sha256':hashlib.sha256((HERE/'严格复核不下单敏感性规则.md').read_bytes()).hexdigest(),
         'note':'Known subset and net amounts unchanged. Unknown payoff magnitudes are not imputed; not shared-account performance.'}
    (HERE/'严格复核不下单敏感性结果.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FOLLOW35_NO_ORDER_SENSITIVITY',json.dumps({k:v for k,v in out.items() if k!='resolved_source_records'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
