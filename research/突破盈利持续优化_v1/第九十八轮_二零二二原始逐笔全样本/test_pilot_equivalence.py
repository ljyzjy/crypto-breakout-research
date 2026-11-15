"""Check bulk replay output against three independently audited pilot samples."""
import json
from pathlib import Path
import pandas as pd
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent; pilot=H.parent/'第九十七轮_原始逐笔一秒回放试点'


def main():
    bulk.runner.guard(start=True); bulk.frozen()
    audit=json.loads((pilot/'原始逐笔试点独立核验.json').read_text(encoding='utf-8'))
    result=json.loads((pilot/'原始逐笔试点结果.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['source_sha256']==bulk.sha(pilot/'原始逐笔试点结果.json')
    wanted={x['observation_id']:x['raw_result'] for x in result['cases']}
    d=pd.read_parquet(bulk.R90/'候选数据/固定十一币双币过滤潜在触价.parquet'); checked=[]
    for (sym,day),g in d.groupby(['contract','day'],sort=True):
        if not set(g.observation_id).intersection(wanted): continue
        out=bulk.execute(bulk.fingerprint(),sym,day,g.to_dict('records'))
        for r in out['rows']:
            if r['observation_id'] not in wanted: continue
            obs=r['observation_id']; actual={k:v for k,v in r.items() if k!='observation_id'}
            assert actual==wanted[obs],obs
            checked.append(obs); print('EXT98_PILOT_MATCH',len(checked),'/',len(wanted),flush=True)
    assert set(checked)==set(wanted)
    doc={'all_checks_pass':True,'cases_checked':checked,'code_sha256':bulk.sha(Path(__file__)),
         'bulk_code_sha256':bulk.sha(H/'run_raw_2022.py'),'pilot_sha256':bulk.sha(pilot/'原始逐笔试点结果.json')}
    (H/'批量回放试点一致性.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT98_PILOT_PASS',len(checked),flush=True)


if __name__=='__main__':main()
