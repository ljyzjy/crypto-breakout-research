from concurrent.futures import ProcessPoolExecutor,as_completed
import factor_engine as e

def task(job):
    scenario,start,end,fee,delay,mode,L=job
    r=e.cached_run(start,end,mode,L,fee,delay);r=e.summary(r);r['scenario']=scenario;return r
def main():
    jobs=[(*c,mode,L) for mode in e.NAMES for L in range(1,11) for c in e.SCENARIOS]
    rows=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        pending={pool.submit(task,j):j for j in jobs}
        for f in as_completed(pending):
            rows.append(f.result())
            if len(rows)%12==0:print(f'completed {len(rows)}/{len(jobs)}',flush=True)
    rows.sort(key=lambda r:(r['mode'],r['leverage'],r['scenario']));e.base.dump(e.ROOT/'metrics.json',rows)
    print('complete',len(rows),'valid',sum(r['valid_for_comparison'] for r in rows),flush=True)
if __name__=='__main__':main()
