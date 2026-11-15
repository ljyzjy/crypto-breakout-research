"""Resume verified 2023 events through a single bounded-memory streaming worker."""
import hashlib,json,shutil,time
from pathlib import Path
import pandas as pd,psutil
import extract_old11_tapes as orig
import stream_tapes_2023 as stream
H=Path(__file__).resolve().parent
def original_key(spec):
    c,d,n,events=spec
    return hashlib.sha256((orig.FP+'|'+c+'|'+d+'|'+str(n)+'|'+'|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest()
def main():
    check=json.loads((H/'流式读取一致性核验.json').read_text(encoding='utf-8'))
    assert check['all_fields_match'] and check['original_fp']==orig.FP and check['stream_fp']==stream.FP
    d=pd.read_parquet(orig.SOURCE)
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]));done=0;reused=0;errors=[]
    print('OLD11_2023_STREAM_TASKS',len(tasks),flush=True)
    for spec in tasks:
        free=shutil.disk_usage(orig.ROOT).free
        if free<stream.DISK_MIN:
            print('OLD11_2023_STREAM_PAUSED_DISK',free,'processed',done,flush=True);break
        wait=0
        while psutil.virtual_memory().available<stream.MEM_MIN:
            time.sleep(3);wait+=1
            if wait%10==0:print('OLD11_2023_STREAM_WAIT_MEMORY',psutil.virtual_memory().available,flush=True)
            if shutil.disk_usage(orig.ROOT).free<stream.DISK_MIN:break
        if shutil.disk_usage(orig.ROOT).free<stream.DISK_MIN:break
        existing=orig.WORK/(original_key(spec)+'.json')
        if existing.exists():
            old=json.loads(existing.read_text(encoding='utf-8'));assert old['status']=='verified';reused+=1
        else:
            r=stream.task(spec)
            if r['status']!='verified':
                errors.append({'contract':r['contract'],'day':r['day'],'error':r.get('error')})
                if 'headroom' in r.get('error',''):break
        done+=1
        if done%5==0:print('OLD11_2023_STREAM',done,'/',len(tasks),'reused',reused,'errors',len(errors),flush=True)
    result={'processed_tasks':done,'total_tasks':len(tasks),'reused_original_tasks':reused,'errors':errors,
            'free_bytes':shutil.disk_usage(orig.ROOT).free,'stream_fp':stream.FP}
    (H/'流式逐笔进度.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_STREAM_STOP',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
