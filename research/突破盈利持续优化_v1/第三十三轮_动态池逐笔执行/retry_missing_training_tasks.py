"""Retry missing training day-tasks in isolation, then safely link verified checkpoints."""
import concurrent.futures,hashlib,json,os
from pathlib import Path
import pandas as pd
import extract_dynamic_tapes as engine
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
SOURCE=PARENT/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet'
ORIGINAL=(ROOT/'work'/'point_in_time_universe33'/'tape').resolve();RETRY=(ROOT/'work'/'point_in_time_universe33'/'training_retry').resolve()
assert ORIGINAL.parent==RETRY.parent;RETRY.mkdir(parents=True,exist_ok=True)
FINGERPRINT='38a1da4b58ea2bb538a522387497125aea3ddd88f0545c7beab90c83f2aa9286'
def main():
    d=pd.read_parquet(SOURCE);cutoff=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    train=d[d.source_year.eq('2024')&(d.quarter_end+60_000<=cutoff)]
    seen=set()
    for f in ORIGINAL.glob('*.json'):
        z=json.loads(f.read_text(encoding='utf-8'));seen.update(r['observation_id'] for r in z['rows'])
    missing=train[~train.observation_id.isin(seen)];keys={(r.contract,r.day) for r in missing.itertuples(index=False)}
    d['needs_next']=(d.quarter_end+60_000-1)//86_400_000>d.trigger_minute//86_400_000
    tasks=[(c,day,bool(n),g.to_dict('records')) for (c,day,n),g in d.groupby(['contract','day','needs_next']) if (c,day) in keys]
    engine.WORK=RETRY;engine.FINGERPRINT=FINGERPRINT
    print('UNIVERSE33_TRAIN_RETRY_TASKS',len(tasks),'missing_events',len(missing),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for r in pool.map(engine.task,tasks):results.append(r)
    linked=0
    for spec,r in zip(tasks,results):
        if r['status']!='verified':continue
        c,day,n,events=spec
        digest=hashlib.sha256((FINGERPRINT+'|'+c+'|'+day+'|'+str(n)+'|'+
              '|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest()
        src=(RETRY/(digest+'.json')).resolve();dst=(ORIGINAL/(digest+'.json')).resolve()
        assert src.parent==RETRY and dst.parent==ORIGINAL and src.exists()
        try:os.link(src,dst);linked+=1
        except FileExistsError:pass
    print('UNIVERSE33_TRAIN_RETRY_COMPLETE',json.dumps({'tasks':len(tasks),'verified':sum(x['status']=='verified' for x in results),
          'linked_new_checkpoints':linked,'errors':[x for x in results if x['status']!='verified']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
