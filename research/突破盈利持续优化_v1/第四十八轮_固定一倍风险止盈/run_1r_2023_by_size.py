"""Resume the identical frozen 2023 tasks, with smaller public archives first."""
import json,shutil
import pandas as pd
import run_1r_2023 as r
def main():
    f=json.loads((r.H/'2023输入冻结哈希.json').read_text(encoding='utf-8'));assert r.sha(r.H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert r.sha(r.I/n)==v
    test=json.loads((r.H/'一倍止盈合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==r.sha(r.H/'exit_1r.py')
    pub=r.P/'第四十七轮_一次重新突破确认';real=json.loads((pub/'无落盘逐笔读取真实样本核验.json').read_text(encoding='utf-8'))
    assert real['all_checks_pass'] and real['stream_code_sha256']==r.sha(pub/'public_tape_stream.py')
    d=pd.read_parquet(r.I/'qualified_entries.parquet');refs=pd.read_parquet(r.I/'reference_2r_paths.parquet');index=r.provenance(d,refs)
    size={}
    for obs,x in index.items():
        z=json.loads(open(x['checkpoint'],encoding='utf-8').read())
        size[obs]=sum(int(a.get('bytes',0)) for a in z['archives'] if a['kind']=='aggTrades') or 10**12
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(max(size.get(e['observation_id'],10**12) for e in x[3]),x[1],x[0]));done=0;errors=[]
    print('EXIT1R48_2023_SIZE_ORDER_TASKS',len(tasks),'events',len(d),'provenance',len(index),flush=True)
    for spec in tasks:
        if shutil.disk_usage(r.ROOT).free<2_200_000_000:break
        z=r.task(spec,index,refs)
        if z['status']!='verified':
            errors.append({'contract':z['contract'],'day':z['day'],'error':z.get('error')})
            if 'headroom' in z.get('error',''):break
        done+=1
        if done%5==0:print('EXIT1R48_2023_SIZE_ORDER',done,'/',len(tasks),'errors',len(errors),flush=True)
    out={'processed_tasks':done,'total_tasks':len(tasks),'errors':errors,'fingerprint':r.FP,
         'free_bytes':shutil.disk_usage(r.ROOT).free,'note':'Archive size affects retrieval order only; no event is excluded and missing paths remain unknown.'}
    (r.H/'2023一倍止盈逐笔进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_2023_SIZE_ORDER_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
