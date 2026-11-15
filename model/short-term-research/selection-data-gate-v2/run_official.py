import gc,hashlib
import availability_engine as e

def main():
    protocol=e.ROOT/'official-protocol.json'
    sha=hashlib.sha256(protocol.read_bytes()).hexdigest()
    freeze=e.ROOT/'official-frozen.json'
    if freeze.exists():assert e.base.read(freeze)['protocol_sha256']==sha
    else:e.base.dump(freeze,dict(created_utc=e.pd.Timestamp.now(tz='UTC').isoformat(),protocol_sha256=sha))
    for path,h in e.base.read(e.ROOT/'frozen.json')['files'].items():
        assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==h,path
    rows=[]
    for scenario,start,end,fee,delay in e.base.read(protocol)['cost_scenarios']:
        for mode in e.NAMES:
            r=e.summary(e.cached_run(start,end,mode,fee,delay));r['scenario']=scenario;rows.append(r)
            e.base.dump(e.ROOT/'official-progress.json',dict(done=len(rows),total=84,scenario=scenario,mode=mode))
            print(len(rows),'/84',scenario,mode,'fee',fee,'valid',r['valid_for_comparison'],flush=True)
        e.prepare.cache_clear();e.hourly_history.cache_clear();gc.collect()
    e.base.dump(e.ROOT/'official-metrics.json',rows)

if __name__=='__main__':main()
