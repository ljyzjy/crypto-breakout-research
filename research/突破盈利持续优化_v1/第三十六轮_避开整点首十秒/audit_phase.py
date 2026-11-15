"""Independent rowwise, standard-library arithmetic and chronology audit."""
import hashlib,json,math
from pathlib import Path
import pandas as pd

H=Path(__file__).resolve().parent;T=H/'冻结输入'
def close(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def keep(t,start):return int(t)-int(start)>=10000
assert not keep(9999,0) and keep(10000,0) and keep(10001,0)

def main():
    expected=json.loads((H/'首十秒过滤训练诊断.json').read_text(encoding='utf-8'))
    frozen=json.loads((H/'输入文件冻结哈希.json').read_text(encoding='utf-8'))
    for name,digest in frozen['source_sha256'].items():assert hashlib.sha256((T/name).read_bytes()).hexdigest()==digest
    sig={x['observation_id']:x for x in pd.read_parquet(T/'动态池逐笔信号筛查.parquet').to_dict('records')}
    ledger=pd.read_parquet(T/'动态池单位收益与风险.parquet').to_dict('records')
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    unknown=sum(x['status'] not in benign for x in sig.values());checked=0;maxerr=0.;checks=[]
    for result in expected['rows']:
        lev=result['leverage'];all_values=[];selected=[];dropped=[]
        for r in ledger:
            if r['variant']!=f'normal_2r_{lev}x':continue
            s=sig[r['observation_id']];ts=int(s['decision_ts']);start=int(s['quarter_start'])
            assert s['status']=='qualified' and r['risk_status']=='verified' and not r['liq_proxy']
            assert int(r['entry_ts'])>=ts+10000 and int(r['exit_ts'])>=int(r['exit_signal_ts'])+5000
            side=int(r['side']);en=float(r['entry_raw'])*(1+side*.0005);ex=float(r['exit_raw'])*(1-side*.0005)
            net=100*(side*(ex/en-1)-.0005-(ex/en)*.0005-float(r['funding']))
            maxerr=max(maxerr,abs(net-float(r['net_pct_notional'])));assert close(net,r['net_pct_notional'])
            all_values.append(net);(selected if keep(ts,start) else dropped).append(net);checked+=1
        for label,vals,u in [('original',all_values,unknown),('phase_filter',selected,unknown),('excluded_early_known_only',dropped,0)]:
            got=result[label];n=len(vals);wins=sum(v>0 for v in vals)
            assert got['verified_events']==n and got['wins']==wins and got['potential_unknown_events']==u
            if n:
                assert close(got['win_rate_pct'],100*wins/n)
                assert close(got['mean_net_pct_notional'],sum(vals)/n)
                neg=-sum(v for v in vals if v<0);pos=sum(v for v in vals if v>0)
                if neg:assert close(got['profit_factor'],pos/neg)
            if n+u:assert close(got['optimistic_unit_win_rate_upper_pct'],100*(wins+u)/(n+u))
        checks.append({'leverage':lev,'all':len(all_values),'selected':len(selected),'excluded':len(dropped)})
    report={'checked_paths':checked,'maximum_net_pct_notional_error':maxerr,'filter_boundary_ms':[9999,10000,10001],
            'potential_unknown_events':unknown,'groups':checks,'all_checks_pass':True,
            'note':'Price references and funding were not independently refetched here; see the source-ledger audit.'}
    (H/'首十秒过滤独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PHASE_AUDIT',json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
