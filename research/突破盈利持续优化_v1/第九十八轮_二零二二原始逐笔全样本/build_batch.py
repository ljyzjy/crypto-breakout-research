"""Materialize all raw replay candidates; never turn missing checkpoints into no-orders."""
import json
from pathlib import Path
import pandas as pd
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent; B=H/'原始逐笔批次'
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}


def main():
    bulk.runner.guard(start=True); spec=bulk.frozen(); fp=bulk.fingerprint()
    test=json.loads((H/'批量回放试点一致性.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['bulk_code_sha256']==bulk.sha(H/'run_raw_2022.py')
    events=pd.read_parquet(bulk.R90/'候选数据/固定十一币双币过滤潜在触价.parquet'); assert len(events)==spec['candidate_count']
    rows={}; archives=[]; work=bulk.runner.ROOT/'raw_2022_full_checkpoints'
    for (sym,day),g in events.groupby(['contract','day'],sort=True):
        es=g.to_dict('records'); p=work/(bulk.runner.key(fp,sym,day,es)+'.json')
        if not p.exists():
            for e in es: rows[e['observation_id']]={'status':'archive_pending'}
            continue
        cp=json.loads(p.read_text(encoding='utf-8')); assert cp['status']=='verified' and cp['fingerprint']==fp
        assert {r['observation_id'] for r in cp['rows']}==set(g.observation_id)
        for r in cp['rows']: rows[r['observation_id']]=r
        archives.append({'contract':sym,'day':day,'checkpoint_path':str(p),'checkpoint_sha256':bulk.sha(p),'archives':cp['archives']})
    assert set(rows)==set(events.observation_id)
    signals=[]; paths=[]
    for e in events.to_dict('records'):
        rec=rows[e['observation_id']]; pre=rec.get('prechecks',{})
        for variant,path in rec.get('paths',{}).items(): paths.append({'observation_id':e['observation_id'],'holding_rule':'original','variant':variant,**path})
        signals.append({**e,**{k:v for k,v in rec.items() if k not in ('prechecks','paths')},
                        'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
    s=pd.DataFrame(signals); p=pd.DataFrame(paths) if paths else pd.DataFrame(columns=['observation_id','holding_rule','variant','status'])
    assert not s.observation_id.duplicated().any() and not p.duplicated(['observation_id','variant']).any()
    B.mkdir(exist_ok=True); s.to_parquet(B/'逐笔信号.parquet',index=False); p.to_parquet(B/'模拟路径.parquet',index=False)
    unknown=s[~s.status.isin(BENIGN)].observation_id.tolist()
    result={'candidate_count':len(s),'completed_groups':len(archives),'expected_groups':spec['group_count'],
            'event_statuses':s.status.value_counts().to_dict(),'unknown_candidates':unknown,
            'path_statuses':p.status.value_counts().to_dict(),'fingerprint':fp,'archives':archives,
            'signals_sha256':bulk.sha(B/'逐笔信号.parquet'),'paths_sha256':bulk.sha(B/'模拟路径.parquet'),
            'code_sha256':bulk.sha(Path(__file__)),'note':'Intermediate paths only; risk, fees, funding, independent audit and unknown hours remain.'}
    (B/'逐笔准备质量.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT98_BATCH',len(s),len(archives),len(unknown),len(p),flush=True)


if __name__=='__main__':main()
