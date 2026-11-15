"""Resume the same frozen tasks, prioritizing smaller previously verified archives."""
import json,shutil
import pandas as pd
import run_retests_later as r
H=r.H;I=r.I
def main():
    frozen=json.loads((H/'跨期输入冻结哈希.json').read_text(encoding='utf-8'));assert r.sha(H/'冻结研究方案.md')==frozen['plan_sha256']
    for n,v in frozen['inputs'].items():assert r.sha(I/n)==v
    synthetic=json.loads((H/'无落盘逐笔读取合成核验.json').read_text(encoding='utf-8'))
    real=json.loads((H/'无落盘逐笔读取真实样本核验.json').read_text(encoding='utf-8'))
    decision=json.loads((H/'一次重试合成时序核验.json').read_text(encoding='utf-8'))
    assert synthetic['all_checks_pass'] and real['all_checks_pass'] and decision['all_checks_pass']
    assert synthetic['stream_code_sha256']==real['stream_code_sha256']==r.sha(H/'public_tape_stream.py')
    d=pd.concat([pd.read_parquet(I/'2024_retry_candidates.parquet'),pd.read_parquet(I/'2026_retry_candidates.parquet')],ignore_index=True)
    assert len(d)==sum(x['candidates'] for x in frozen['counts'].values()) and d.observation_id.is_unique
    needed=set(d.observation_id);index=r.archive_index(needed);provenance=json.loads((I/'provenance.json').read_text(encoding='utf-8'));sizes={}
    for record in provenance:
        obs=record['observation_id']
        if obs not in needed:continue
        if record['source']=='reused_tape':archives=json.loads(open(record['old_checkpoint'],encoding='utf-8').read())['archives']
        elif record['source']=='new_tape':archives=record['archives']
        else:continue
        sizes[obs]=sum(int(x.get('bytes',0)) for x in archives if x['kind']=='aggTrades') or 10**12
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(max(sizes.get(e['observation_id'],10**12) for e in x[3]),x[1],x[0]))
    done=0;errors=[];print('RETEST47_LATER_SIZE_ORDER_TASKS',len(tasks),'events',len(d),'provenance',len(index),flush=True)
    for spec in tasks:
        if shutil.disk_usage(r.ROOT).free<2_200_000_000:break
        z=r.task(spec,index)
        if z['status']!='verified':
            errors.append({'contract':z['contract'],'day':z['day'],'error':z.get('error')})
            if 'headroom' in z.get('error',''):break
        done+=1
        if done%5==0:print('RETEST47_LATER_SIZE_ORDER',done,'/',len(tasks),'errors',len(errors),flush=True)
    out={'processed_tasks':done,'total_tasks':len(tasks),'errors':errors,'fingerprint':r.FP,
         'free_bytes':shutil.disk_usage(r.ROOT).free,'note':'Size changes retrieval order only; all missing results remain unknown.'}
    (H/'跨期重试逐笔进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_LATER_SIZE_ORDER_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
