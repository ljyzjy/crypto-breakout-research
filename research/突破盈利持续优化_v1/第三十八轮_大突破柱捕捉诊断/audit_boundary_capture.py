"""Independently recompute post-close labels and large-bar entry accounting."""
import json,math
from decimal import Decimal
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
def close(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def is_big(op,cl):return abs(Decimal(str(cl))-Decimal(str(op)))>=Decimal('.01')*Decimal(str(op))
assert is_big('100','101') and is_big('100','99') and not is_big('100','100.9999')

def main():
    result=json.loads((H/'收盘越界大柱诊断.json').read_text(encoding='utf-8'))
    sample=json.loads((H/'十五分钟行情样本独立核验.json').read_text(encoding='utf-8'))
    bad={(x['contract'],int(x['quarter_start'])) for x in sample['samples'] if x['status']!='verified'}
    bars={(r.contract,int(r.open_time)):r for r in pd.read_parquet(H/'候选十五分钟行情.parquet').itertuples(index=False)}
    sig=pd.read_parquet(I/'baseline_signal.parquet').to_dict('records');info={r['observation_id']:r for r in sig}
    labels={};dirs={};missing=0
    for e in sig:
        k=(e['contract'],int(e['quarter_start']));b=bars.get(k)
        if b is None or k in bad or b.volume<=0:missing+=1;continue
        direction=(1 if b.close>b.open else -1 if b.close<b.open else 0)
        ok=(direction==1 and e['long_known_eligible']) or (direction==-1 and e['short_known_eligible'])
        labels[e['observation_id']]=bool(is_big(b.open,b.close) and ok and ((direction==1 and b.close>e['upper']) or (direction==-1 and b.close<e['lower'])));dirs[e['observation_id']]=direction
    large={k for k,v in labels.items() if v}
    assert len(labels)==result['classified_candidate_quarters'] and len(large)==result['candidate_large_quarters']
    assert missing==result['unclassified_candidate_quarters']
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified','no_follow_known'}
    checked=0;groups=[];maximum_error=0.
    for row in result['rows']:
        name=row['strategy'];lev=row['leverage'];phase=row['exclude_first_10_seconds'];variant=f'normal_2r_{lev}x'
        signal=pd.read_parquet(I/f'{name}_signal.parquet').to_dict('records')
        paths=pd.read_parquet(I/f'{name}_paths.parquet').to_dict('records')
        ledger=pd.read_parquet(I/f'{name}_ledger.parquet').to_dict('records')
        unknown={x['observation_id'] for x in signal if x['status'] not in benign}
        unknown.update(x['observation_id'] for x in paths if x['variant']==variant and x['status']!='verified')
        entries=[]
        for x in ledger:
            if x['variant']!=variant:continue
            if x['status']!='verified' or x['risk_status']!='verified' or x['liq_proxy']:
                unknown.add(x['observation_id']);continue
            entries.append(x)
        unknown-=set(x['observation_id'] for x in entries)
        if phase:entries=[x for x in entries if int(x['decision_ts'])-int(info[x['observation_id']]['quarter_start'])>=10000]
        with_label=[x for x in entries if x['observation_id'] in labels]
        matches=[]
        for x in with_label:
            e=info[x['observation_id']];side=int(x['side']);en=float(x['entry_raw'])*(1+side*.0005);ex=float(x['exit_raw'])*(1-side*.0005)
            net=100*(side*(ex/en-1)-.0005-(ex/en)*.0005-float(x['funding']))
            maximum_error=max(maximum_error,abs(net-float(x['net_pct_notional'])));assert close(net,x['net_pct_notional'])
            if x['observation_id'] in large and side==dirs[x['observation_id']] and int(x['entry_ts'])<int(e['quarter_end']):matches.append(x)
            checked+=1
        u=len(unknown&large);wins=sum(float(x['net_pct_notional'])>0 for x in matches)
        assert row['verified_entries']==len(entries) and row['verified_entries_with_bar_label']==len(with_label)
        assert row['large_direction_entries']==len(matches) and row['large_direction_entries_net_positive']==wins
        match_ids={x['observation_id'] for x in matches};other=[x for x in with_label if x['observation_id'] not in match_ids]
        assert row['other_classified_entries']==len(other)
        assert row['other_classified_entries_net_positive']==sum(float(x['net_pct_notional'])>0 for x in other)
        if other:assert close(row['other_classified_entries_mean_net_pct_notional'],sum(float(x['net_pct_notional']) for x in other)/len(other))
        assert row['large_candidate_count']==len(large) and row['unknown_large_candidates']==u
        if matches:assert close(row['large_direction_entries_mean_net_pct_notional'],sum(float(x['net_pct_notional']) for x in matches)/len(matches))
        if with_label:assert close(row['large_entry_share_of_classified_entries_pct'],100*len(matches)/len(with_label))
        if large:
            assert close(row['observed_large_candidate_entry_rate_pct'],100*len(matches)/len(large))
            assert close(row['optimistic_large_candidate_entry_upper_pct'],100*(len(matches)+u)/len(large))
        groups.append({'strategy':name,'first_10_seconds_excluded':phase,'leverage':lev,'verified_entries':len(entries),'large_direction_entries':len(matches)})
    sensitivity_checked=False
    out={'candidate_labels_checked':len(labels),'large_candidate_labels_checked':len(large),'entry_rows_recomputed':checked,
         'maximum_net_pct_notional_error':maximum_error,'sample_minute_to_quarter_pass':sample['sample_pass'],
         'sample_minute_to_quarter_total':sample['sample_count'],'exact_1pct_boundaries_checked':True,
         'groups':groups,'strict_no_order_capture_sensitivity_checked':sensitivity_checked,'all_checks_pass':True,
         'note':'Large labels are post-close; no shared-account or ex-ante selection inference.'}
    (H/'收盘越界大柱独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE38_BOUNDARY_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
