import json,hashlib
import pool_engine as p
from run_sizing import SCENARIOS

def main():
    names=['protocol.json','pool_engine.py','execution.py','execution-provenance.json','test_pool.py','run_pool.py','execution-data-manifest.json','diagnosis_protocol.json','diagnosis.json']
    frozen={n:hashlib.sha256((p.ROOT/n).read_bytes()).hexdigest() for n in names}
    target=p.ROOT/'frozen.json'
    if target.exists():assert p.old.base.read(target)==frozen
    else:p.old.base.dump(target,frozen)
    manifest=p.old.base.read(p.ROOT/'execution-data-manifest.json')
    for name,expected in manifest['old_hashes'].items():assert hashlib.sha256((p.OLD/name).read_bytes()).hexdigest()==expected,name
    rows=[]
    for mode in p.VARIANTS:
        for window,start,end,fee,tf,delay in SCENARIOS:
            r=p.cached_run(start,end,mode,fee,tf,delay);row=p.summary(r);row['window']=window;rows.append(row)
            if mode=='pool_control':
                old=p.old.cached_run(start,end,'auto_budget2',fee,tf,delay)
                for field in ('curve','orders','return_pct','max_drawdown','fees','slippage_cost','cash_min','guard_activations'):
                    assert r[field]==old[field],field
                assert [{k:v for k,v in t.items() if k not in ('stop_distance','planned_stop_loss')} for t in r['trades']]==old['trades']
            print(mode,window,tf,fee,delay,'return',round(r['return_pct'],4),'DD',round(r['max_drawdown'],4),'trades',r['trade_count'],'valid',r['valid_for_comparison'],flush=True)
    p.old.base.dump(p.ROOT/'metrics.json',rows)
    print('42 fixed scenarios completed; no retuning',flush=True)

if __name__=='__main__':main()
