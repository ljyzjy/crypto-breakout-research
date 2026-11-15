"""Recover small, late training archives while the first early archive is slow."""
import concurrent.futures,json,sys
import pandas as pd
import extract_pullback_tapes as run
from pullback_paths import simulate_pullback

def main():
    run.loader.WORK=run.WORK;run.loader.FINGERPRINT=run.FINGERPRINT;run.loader.simulate_follow=simulate_pullback
    d=pd.read_parquet(run.SOURCE);q=json.loads((run.ORIG/'动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    originals={(r['contract'],r['day'],bool(r['needs_next'])):r for r in q['archives'] if r['status']=='verified'}
    month=sys.argv[1] if len(sys.argv)>1 else '2024-04'
    size_class=sys.argv[2] if len(sys.argv)>2 else 'small'
    assert month in ('2024-02','2024-03','2024-04')
    assert size_class in ('small','medium')
    tasks=[]
    for (contract,day,needs),g in d.groupby(['contract','day','needs_next']):
        key=(contract,day,bool(needs));rec=originals[key];a=[x for x in rec['archives'] if x['kind']=='aggTrades']
        # This ordering uses only archive date and byte size, not trade returns.
        size=sum(x['bytes'] for x in a)
        chosen_size=(size<10_000_000) if size_class=='small' else (10_000_000<=size<80_000_000)
        if not (day.startswith(month+'-') and chosen_size):continue
        tasks.append((contract,day,bool(needs),g.to_dict('records'),{x['day']:x['sha256'] for x in a}))
    tasks.sort(key=lambda x:(x[1],x[0]));print('PULLBACK37_SMALL_TASKS',len(tasks),flush=True);errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fs=[pool.submit(run.guarded_task,x) for x in tasks]
        for i,f in enumerate(concurrent.futures.as_completed(fs),1):
            r=f.result()
            if r['status']!='verified':errors.append({'contract':r['contract'],'day':r['day'],'error':r.get('error')})
            print('PULLBACK37_SMALL',i,'/',len(tasks),flush=True)
    print('PULLBACK37_SMALL_COMPLETE',json.dumps({'tasks':len(tasks),'errors':errors},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
