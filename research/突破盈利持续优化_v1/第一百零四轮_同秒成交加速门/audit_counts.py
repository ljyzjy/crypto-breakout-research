"""Independently count fixed audit windows with chunked pandas parsing."""
import json
from pathlib import Path
import sys
import zipfile
import numpy as np
import pandas as pd
import requests
import count_same_phase as main

H=Path(__file__).resolve().parent


def independent_counts(path,windows):
    with zipfile.ZipFile(path) as z:
        names=z.namelist();assert len(names)==1
        head=z.open(names[0]).readline().decode('utf-8-sig').strip().split(',')
    header=head[0].strip().lower() in ('id','trade_id')
    names=['id','price','qty','quote_qty','time','is_buyer_maker']
    use=['time'] if header else [4]
    counts=np.zeros(len(windows),dtype='int64')
    for part in pd.read_csv(path,compression='zip',header=0 if header else None,names=None if header else names,usecols=use,dtype=str,chunksize=120000):
        main.bulk.runner.guard();times=pd.to_numeric(part.iloc[:,0],errors='raise').to_numpy(dtype='int64')
        for i,(a,b) in enumerate(windows):counts[i]+=int(((times>a)&(times<b)).sum())
    return counts.tolist()


def main_audit():
    main.bulk.runner.guard(start=True);f=main.frozen();path=H/'同秒计数结果.json';source=json.loads(path.read_text(encoding='utf-8'))
    assert source['code_sha256']==main.bulk.sha(H/'count_same_phase.py') and source['fingerprint']==main.fingerprint()
    by={r['observation_id']:r for r in source['events']};checked=[];unresolved=[]
    for obs in f['audit_sample_ids']:
        r=by[obs];status=r['status']
        if status=='unknown_source':unresolved.append(obs);continue
        t=int(r['decision_ts']);windows=[(t-j*900000,t-j*900000+1000) for j in range(1,21)]+[(t,t+1000)]
        counts=[0]*21
        for a in r['archives']:
            p=Path(a['path']);assert main.bulk.sha(p)==a['sha256']
            c=requests.get(a['url']+'.CHECKSUM',timeout=(15,50));c.raise_for_status();fields=c.text.strip().split()
            assert fields[0].lower()==a['sha256'] and Path(fields[1]).name==p.name
            counts=[x+y for x,y in zip(counts,independent_counts(p,windows))]
        assert counts[:-1]==r['previous_counts'] and counts[-1]==r['current_n'] and sum(counts[:-1])==r['previous_total']
        if r['current_n']!=r['stored_n']:assert status=='unknown_current_count_mismatch' and r['accepted'] is None
        elif not r['previous_total']:assert status=='unknown_zero_history' and r['accepted'] is None
        else:assert status=='verified' and r['accepted']==(40*r['current_n']>=3*r['previous_total'])
        checked.append(obs);print('EXT104_AUDIT',len(checked),'/',len(f['audit_sample_ids']),flush=True)
    out={'all_checks_pass':True,'fixed_sample_count':len(f['audit_sample_ids']),'samples_checked':len(checked),'unresolved_samples':unresolved,
         'source_sha256':main.bulk.sha(path),'code_sha256':main.bulk.sha(Path(__file__)),
         'note':'Independent raw timestamp parser; missing samples remain unknown, not rejected.'}
    (H/'同秒计数独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT104_AUDIT_PASS',len(checked),len(unresolved),flush=True)


if __name__=='__main__':main_audit()
