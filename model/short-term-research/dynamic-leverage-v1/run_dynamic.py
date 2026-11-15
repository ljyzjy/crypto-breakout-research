from concurrent.futures import ProcessPoolExecutor,as_completed
import dynamic_engine as e

def task(job):
    scenario,start,end,fee,delay,mode=job;r=e.summary(e.cached_run(start,end,mode,fee,delay));r['scenario']=scenario;return r
def main():
    jobs=[(*c,mode) for mode in e.NAMES for c in e.SCENARIOS];rows=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(task,j) for j in jobs]):
            r=f.result();rows.append(r);print(f'{len(rows)}/{len(jobs)} {r["mode"]} {r["scenario"]}',flush=True)
    rows.sort(key=lambda r:(r['mode'],r['scenario']));e.base.dump(e.ROOT/'metrics.json',rows);print('completed',len(rows),flush=True)
if __name__=='__main__':main()
