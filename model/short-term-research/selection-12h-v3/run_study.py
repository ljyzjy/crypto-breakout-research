import hashlib,gc
import cadence_engine as e

def main():
    assert e.base.read(e.ROOT/'preflight.json')['passed']
    for path,sha in e.base.read(e.ROOT/'frozen.json')['files'].items():
        assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha,path
    rows=[]
    for scenario,start,end,fee,delay in e.SCENARIOS:
        for mode in e.NEW_NAMES:
            r=e.summary(e.cached_run(start,end,mode,fee,delay));r['scenario']=scenario;rows.append(r)
            e.base.dump(e.ROOT/'progress.json',dict(done=len(rows),total=60,scenario=scenario,mode=mode))
            print(len(rows),'/60',scenario,mode,r['valid_for_comparison'],flush=True)
        e.prepare.cache_clear();e.previous.prepare.cache_clear();e.hourly_history.cache_clear();gc.collect()
    e.base.dump(e.ROOT/'metrics.json',rows)

if __name__=='__main__':main()
