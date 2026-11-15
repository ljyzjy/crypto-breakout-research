import pool_dynamic_engine as e
def main():
    assert e.base.read(e.ROOT/'preflight.json')['passed']
    rows=[];done=0
    # Reuse one period matrix across six selectors/overlays, limit memory on this laptop.
    for scenario,start,end,fee,delay in e.SCENARIOS:
        for mode in e.ALL_NAMES:
            r=e.summary(e.cached_run(start,end,mode,fee,delay));r['scenario']=scenario;rows.append(r);done+=1
            e.base.dump(e.ROOT/'progress.json',dict(done=done,total=80,scenario=scenario,mode=mode))
            print(done,'/80',mode,scenario,'valid',r['valid_for_comparison'],flush=True)
    e.base.dump(e.ROOT/'metrics.json',rows)
if __name__=='__main__':main()
