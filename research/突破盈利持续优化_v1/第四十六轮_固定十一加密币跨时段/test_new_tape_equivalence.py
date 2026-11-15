"""Redownload two pre-existing events and compare all execution-critical fields."""
import json,math
from pathlib import Path
import pandas as pd
import stream_fixed11_tapes as stream
H=Path(__file__).resolve().parent;I=H/'逐笔冻结输入'
def equal(a,b,where):
    if isinstance(a,(float,int)) and not isinstance(a,bool):
        assert math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-12),(where,a,b)
    else:assert a==b,(where,a,b)
def main():
    plan=pd.read_parquet(H/'逐笔复用计划.parquet');candidates=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True).set_index('observation_id')
    old=pd.concat([pd.read_parquet(I/'old_signal.parquet'),pd.read_parquet(I/'backup_signal.parquet')],ignore_index=True).set_index('observation_id')
    paths=pd.concat([pd.read_parquet(I/'old_paths.parquet'),pd.read_parquet(I/'backup_paths.parquet')],ignore_index=True)
    checked=[]
    for year in ('2024','2026'):
        p=plan[(plan.source_year.eq(year))&plan.reason.eq('exact_execution_inputs')].sort_values(['contract','day','observation_id'])
        eligible=[obs for obs in p.observation_id if old.loc[obs,'status']=='qualified'];assert eligible
        obs=eligible[0];e=candidates.loc[obs].to_dict();e['observation_id']=obs
        spec=(e['contract'],e['day'],bool(e['needs_next']),[e]);result=stream.task(spec)
        assert result['status']=='verified',result
        row=result['rows'][0];before=old.loc[obs];assert row['status']==before['status']=='qualified'
        for key in ('side','decision_ts','signal_close','entry_exec_ts','raw_entry_5s','five_count','buy_notional','sell_notional','five_imbalance','stop_price','level'):
            equal(row[key],before[key],(obs,key))
        for lev in (10,20):equal(row['prechecks'][str(lev)],before[f'precheck_{lev}x'],(obs,'precheck',lev))
        prior=paths[paths.observation_id.eq(obs)];assert set(prior.variant)==set(row['paths'])
        for record in prior.to_dict('records'):
            variant=record.pop('variant');record.pop('observation_id');actual=row['paths'][variant]
            for key,value in record.items():
                if pd.isna(value):continue
                assert key in actual,(obs,variant,key);equal(actual[key],value,(obs,variant,key))
        checked.append({'year':year,'observation_id':obs,'paths_checked':len(prior),'archives':result['archives']})
        print('FIXED11_46_TAPE_EQUIVALENCE',len(checked),'/2',flush=True)
    out={'all_checks_pass':True,'stream_fingerprint':stream.FP,'samples':checked,
         'paths_checked':sum(x['paths_checked'] for x in checked),'note':'Same public archives, critical signals and execution paths; actual fills remain unknown.'}
    (H/'新逐笔读取一致性核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_TAPE_EQUIVALENCE_PASS',len(checked),flush=True)
if __name__=='__main__':main()
