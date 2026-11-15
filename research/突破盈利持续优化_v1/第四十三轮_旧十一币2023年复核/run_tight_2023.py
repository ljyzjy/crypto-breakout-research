"""Resume 2023 replay with three independently fingerprinted checkpoint sets."""
import hashlib,json,shutil,time
from pathlib import Path
import pandas as pd,psutil
import extract_old11_tapes as original
import stream_tapes_2023 as normal
import stream_tapes_2023_tight as tight
H=Path(__file__).resolve().parent
def original_key(spec):
    c,d,n,events=spec
    return hashlib.sha256((original.FP+'|'+c+'|'+d+'|'+str(n)+'|'+'|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest()
def main():
    check=json.loads((H/'小块读取一致性核验.json').read_text(encoding='utf-8'))
    assert check['all_fields_match'] and check['original_fp']==original.FP and check['normal_fp']==normal.FP and check['tight_fp']==tight.FP
    d=pd.read_parquet(original.SOURCE)
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]));done=0;reused={'original':0,'normal':0,'tight':0};errors=[]
    print('OLD11_TIGHT_TASKS',len(tasks),flush=True)
    for spec in tasks:
        if shutil.disk_usage(original.ROOT).free<tight.DISK_MIN:break
        wait=0
        while psutil.virtual_memory().available<tight.MEM_MIN:
            time.sleep(3);wait+=1
            if wait%10==0:print('OLD11_TIGHT_WAIT_MEMORY',psutil.virtual_memory().available,flush=True)
            if shutil.disk_usage(original.ROOT).free<tight.DISK_MIN:break
        if shutil.disk_usage(original.ROOT).free<tight.DISK_MIN:break
        options=[('original',original.WORK/(original_key(spec)+'.json')),
                 ('normal',normal.WORK/(normal.key_for(spec)+'.json')),
                 ('tight',tight.WORK/(tight.key_for(spec)+'.json'))]
        found=False
        for label,path in options:
            if path.exists():
                old=json.loads(path.read_text(encoding='utf-8'));assert old['status']=='verified';reused[label]+=1;found=True;break
        if not found:
            r=tight.task(spec)
            if r['status']!='verified':
                errors.append({'contract':r['contract'],'day':r['day'],'error':r.get('error')})
                if 'headroom' in r.get('error',''):break
        done+=1
        if done%5==0:print('OLD11_TIGHT',done,'/',len(tasks),'reused',sum(reused.values()),'errors',len(errors),flush=True)
    result={'processed_tasks':done,'total_tasks':len(tasks),'reused':reused,'errors':errors,
            'free_bytes':shutil.disk_usage(original.ROOT).free,'tight_fp':tight.FP}
    (H/'小块逐笔进度.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_TIGHT_STOP',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
