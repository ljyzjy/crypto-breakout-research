"""Resume 2023 replay one archive at a time with extra disk and RAM headroom."""
import json,shutil,time
import pandas as pd,psutil
import extract_old11_tapes as run
def main():
    d=pd.read_parquet(run.SOURCE)
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]));errors=[];done=0
    print('OLD11_2023_LOW_MEMORY_TASKS',len(tasks),flush=True)
    for task in tasks:
        free=shutil.disk_usage(run.ROOT).free
        if free<2_200_000_000:
            print('OLD11_2023_PAUSED_DISK_HEADROOM',free,'completed',done,'/',len(tasks),flush=True);break
        waits=0
        while psutil.virtual_memory().available<2_000*1024**2:
            time.sleep(3);waits+=1
            if waits%10==0:print('OLD11_2023_WAIT_MEMORY',psutil.virtual_memory().available,flush=True)
            if shutil.disk_usage(run.ROOT).free<2_200_000_000:break
        if shutil.disk_usage(run.ROOT).free<2_200_000_000:
            print('OLD11_2023_PAUSED_DISK_HEADROOM',shutil.disk_usage(run.ROOT).free,flush=True);break
        r=run.task(task);done+=1
        if r['status']!='verified':errors.append({'contract':r['contract'],'day':r['day'],'error':r.get('error')})
        if done%5==0:print('OLD11_2023_LOW_MEMORY',done,'/',len(tasks),'errors',len(errors),flush=True)
    print('OLD11_2023_LOW_MEMORY_STOP',json.dumps({'processed_tasks':done,'total_tasks':len(tasks),'errors':errors,
      'free_bytes':shutil.disk_usage(run.ROOT).free},ensure_ascii=False),flush=True)
    if done==len(tasks) and not errors:run.main() # all tasks already checkpointed; no extra downloads
if __name__=='__main__':main()
