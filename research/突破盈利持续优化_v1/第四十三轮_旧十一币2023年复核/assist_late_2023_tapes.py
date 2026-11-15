"""Recover late-2023 archives while the main worker begins at the year's start."""
import concurrent.futures,json
import pandas as pd
import extract_old11_tapes as run
def main():
    d=pd.read_parquet(run.SOURCE);d=d[d.day.ge('2023-07-01')]
    tasks=[(sym,day,bool(needs),g.to_dict('records')) for (sym,day,needs),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]),reverse=True)
    print('OLD11_2023_LATE_TASKS',len(tasks),flush=True);errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for i,f in enumerate(concurrent.futures.as_completed([pool.submit(run.task,t) for t in tasks]),1):
            r=f.result()
            if r['status']!='verified':errors.append({'contract':r['contract'],'day':r['day'],'error':r.get('error')})
            if i%10==0:print('OLD11_2023_LATE',i,'/',len(tasks),flush=True)
    print('OLD11_2023_LATE_COMPLETE',json.dumps({'tasks':len(tasks),'errors':errors},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
