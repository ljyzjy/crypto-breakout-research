from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib,json
import rotation_engine as e

def group(job):
    venue,label,start,end,fee,delay,tf=job;rows=[]
    for mode in e.NAMES:
        for lev in range(1,11) if venue=='perp' else (1,):
            r=e.cached_run(start,end,mode,venue,lev,fee,delay,tf);r=e.summary(r);r['scenario']=label;rows.append(r)
        print('completed',venue,label,tf,mode,flush=True)
    return rows

def main():
    assert e.base.read(e.ROOT/'preflight-validation.json')['passed']
    names=('protocol.json','rotation_engine.py','acquire_data.py','test_rotation.py','run_rotation.py','data-manifest.json','contract-map.json','coverage-plan.json')
    frozen={n:hashlib.sha256((e.ROOT/n).read_bytes()).hexdigest() for n in names};dest=e.ROOT/'frozen.json'
    if dest.exists():assert e.base.read(dest)==frozen
    else:e.base.dump(dest,frozen)
    for name,sha in e.manifest()['old_hashes'].items():assert hashlib.sha256((e.RESEARCH/name).read_bytes()).hexdigest()==sha
    jobs=[(venue,label,start,end,fee,delay,'5m') for venue in ('spot','perp') for label,start,end,fee,delay in e.SCENARIOS]
    jobs.append(('spot','main1h','2025-01-01','2026-10-31',.001,0,'1h'))
    rows=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(group,j) for j in jobs]):
            rows.extend(f.result());e.base.dump(e.ROOT/'progress.json',{'done':len(rows),'total':268})
    rows.sort(key=lambda r:(r['venue'],r['mode'],r['leverage'],r['scenario']))
    assert len(rows)==268;e.base.dump(e.ROOT/'metrics.json',rows)
    print(json.dumps({'complete':True,'scenarios':len(rows),'valid':sum(r['valid_for_comparison'] for r in rows),'halted':sum(r['halted'] for r in rows)}),flush=True)

if __name__=='__main__':main()
