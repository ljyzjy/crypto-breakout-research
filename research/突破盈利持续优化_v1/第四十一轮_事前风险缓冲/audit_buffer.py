"""Independently verify P5 thresholds and selected-path cost accounting."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    d=json.loads((H/'事前缓冲训练诊断.json').read_text(encoding='utf-8'));prior=json.loads((I/'dual_result.json').read_text(encoding='utf-8'))
    sig=pd.read_parquet(I/'signal.parquet').set_index('observation_id');scores=pd.read_parquet(H/'P5缓冲事前决定.parquet')
    ledger=pd.read_parquet(I/'ledger.parquet').to_dict('records');groups=[];max_error=0.
    for z in d['rows']:
        lev=z['leverage'];q=scores[scores.leverage.eq(lev)];chosen=q[q.decision.eq('selected_known_inputs')]
        ids=set(chosen.observation_id);assert ids==set(z['selected_observation_ids'])
        for r in chosen.itertuples(index=False):
            e=sig.loc[r.observation_id];side=int(e.side);x=side*(float(e.raw_entry_5s)*(1+side*.0005)-float(e.signal_close))/float(e.atr)
            assert x<=.125 and near(x,r.buffer_ratio_at_p5) and int(e.entry_exec_ts)>=int(e.decision_ts)+5000
        old=set(next(x for x in prior['rows'] if x['leverage']==lev)['verified_observation_ids']);assert ids.issubset(old)
        entries=[r for r in ledger if r['variant']==f'normal_2r_{lev}x' and r['observation_id'] in ids]
        original=[r for r in ledger if r['variant']==f'normal_2r_{lev}x' and r['observation_id'] in old]
        values=[]
        for r in entries:
            side=int(r['side']);en=r['entry_raw']*(1+side*.0005);ex=r['exit_raw']*(1-side*.0005)
            net=side*(ex/en-1)-.0005-.0005*ex/en-r['funding'];max_error=max(max_error,abs(net-r['net_per_unit_notional']))
            assert near(net,r['net_per_unit_notional']);values.append(net)
        wins=sum(v>0 for v in values);u=sum(x in ('source_unknown','market_unknown','precheck_unknown','feature_unknown') for x in q.decision)
        assert len(entries)==z['buffer_verified_events'] and wins==z['buffer_net_wins'] and u==z['remaining_unknown_events']
        if entries:assert near(z['buffer_mean_net_pct_notional'],100*sum(values)/len(entries)) and near(z['buffer_win_rate_pct'],100*wins/len(entries))
        assert z['prior_unsafe_fills']==sum(x['reason']=='filled_beyond_risk_budget' for x in original)
        assert z['buffer_unsafe_fills']==sum(x['reason']=='filled_beyond_risk_budget' for x in entries)
        if len(entries)+u:assert near(z['optimistic_unit_win_rate_upper_pct'],100*(wins+u)/(len(entries)+u))
        groups.append({'leverage':lev,'events':len(entries),'wins':wins,'unknown':u,'unsafe_fills':z['buffer_unsafe_fills']})
    out={'groups':groups,'maximum_net_fraction_error':max_error,'all_checks_pass':True,
         'note':'Small exploratory subgroup, no real fills or account concurrency reconstructed.'}
    (H/'缓冲结果独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BUFFER41_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
