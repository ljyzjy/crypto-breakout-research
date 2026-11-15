"""Audit retry checkpoint provenance and decision/entry time ordering."""
import hashlib,json
from pathlib import Path
import pandas as pd
import run_retests_2023 as y23,run_retests_later as later
H=Path(__file__).resolve().parent
def main():
    test=json.loads((H/'一次重试合成时序核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['decision_code_sha256']==hashlib.sha256((H/'retest_decision.py').read_bytes()).hexdigest()
    reports=[]
    for year,runner,root in [('2023',y23,H/'2023冻结输入'),('2024',later,H/'跨期冻结输入'),('2026',later,H/'跨期冻结输入')]:
        name='retry_candidates.parquet' if year=='2023' else f'{year}_retry_candidates.parquet'
        events=pd.read_parquet(root/name);old_index=runner.archive_index(set(events.observation_id));done=0;pending=0;statuses={}
        for (sym,day,n),g in events.groupby(['contract','day','needs_next']):
            spec=(sym,day,bool(n),g.to_dict('records'));file=runner.WORK/(runner.key_for(spec)+'.json')
            if not file.exists():pending+=len(g);continue
            z=json.loads(file.read_text(encoding='utf-8'));assert z['status']=='verified' and {x['observation_id'] for x in z['rows']}==set(g.observation_id)
            origin={e['observation_id']:e for e in g.to_dict('records')};archives={(x['kind'],x['day']):x['sha256'] for x in z['archives']}
            for r in z['rows']:
                obs=r['observation_id'];e=origin[obs];status=r['status'];statuses[status]=statuses.get(status,0)+1;done+=1
                assert e['status']=='flow_filter_not_met' and int(e['side'])*(float(e['raw_entry_5s'])-float(e['level']))<=0
                prior=old_index.get(obs)
                if prior and status not in ('old_archive_provenance_missing','official_day_source_changed','daily_monthly_ohlc_mismatch','official_agg_source_changed'):
                    assert archives[('klines',day)]==prior['daily_sha256']
                    for (kind,date),digest in archives.items():
                        if kind=='aggTrades':assert prior['agg_sha256'][date]==digest
                if 'retest_ts' not in r:continue
                assert int(r['retest_ts'])>=int(e['entry_exec_ts']) and int(r['retest_ts'])<int(e['quarter_end'])
                if 'decision_ts' in r:
                    assert int(r['decision_ts'])==int(r['retest_ts']) and int(r['entry_exec_ts'])>=int(r['retest_ts'])+5000
                    assert int(r['entry_exec_ts'])<int(e['quarter_end']) and int(r['side'])==int(e['side'])
                if status=='qualified':
                    for variant,p in r['paths'].items():
                        lev=int(variant.rsplit('_',1)[1].rstrip('x'));assert r['prechecks'][str(lev)]=='passed'
                        if p['status']=='verified':
                            assert int(p['entry_ts'])>=int(r['entry_exec_ts'])+5000 and int(p['entry_ts'])<int(e['quarter_end'])
                            assert int(p['exit_ts'])>=int(p['exit_signal_ts'])+5000
        assert done+pending==len(events)
        reports.append({'year':year,'retry_candidates':len(events),'verified_source_records':done,'pending_candidates':pending,'statuses':statuses})
    out={'all_checks_pass':True,'periods':reports,'note':'Timing and source provenance checks; unresolved source statuses remain unknown.'}
    (H/'重试来源时序独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_CAUSALITY_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
