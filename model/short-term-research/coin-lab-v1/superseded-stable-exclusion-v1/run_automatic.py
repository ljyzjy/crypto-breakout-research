import json,hashlib
import automatic_engine as a
from run_sizing import SCENARIOS
ROOT=a.ROOT

def main():
    paths=[ROOT/x for x in ('automatic-protocol.json','automatic_engine.py','download_pool.py','download_execution.py','pool-data-manifest.json','execution-manifest.json','run_automatic.py','test_coin_lab.py')]
    frozen={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    fp=ROOT/'automatic-frozen.json'
    if fp.exists():assert a.base.read(fp)==frozen
    else:a.base.dump(fp,frozen)
    rows=[]
    for policy in a.AUTO:
        for window,start,end,fee,tf,delay in SCENARIOS:
            r=a.cached_run(start,end,policy,fee,tf,delay)
            d={k:v for k,v in a.c.summary(r).items() if k!='selection_trace'};d['window']=window;rows.append(d)
            print(policy,window,tf,fee,delay,'ROI',round(r['return_pct'],4),'DD',round(r['max_drawdown'],4),'trades',r['trade_count'],'valid',r['valid_for_comparison'],flush=True)
    a.base.dump(ROOT/'automatic-metrics.json',rows)
    print('14 automatic scenarios complete',flush=True)

if __name__=='__main__':main()
