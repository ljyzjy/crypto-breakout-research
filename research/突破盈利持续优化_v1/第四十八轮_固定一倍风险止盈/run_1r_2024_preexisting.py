"""Backfill 1R only for already completed, stable one-second checkpoints."""
import json,shutil,sys,time
from pathlib import Path
import pandas as pd,psutil
import run_1r_later as r,public_range
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;E=P/'第五十一轮_缩短市价入场延迟'
sys.path.insert(0,str(E));import run_entry_1s as early,combined_2024_runner as dual
def main():
    year='2024';I=H/f'{year}冻结输入';f=json.loads((H/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
    assert r.sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert r.sha(I/n)==v
    audit=json.loads((H/'分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['range_code_sha256']==r.sha(H/'public_range.py')
    assert audit['stream_code_sha256']==r.sha(P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py')
    d=pd.read_parquet(I/'qualified_entries.parquet');refs=pd.read_parquet(I/'reference_2r_paths.parquet');index=r.provenance(year,d,refs)
    fp=dual.fingerprint_1r();fp51=early.fingerprint(year);work=ROOT/'work'/'exit1r48_2024'/'tape';work.mkdir(parents=True,exist_ok=True)
    w51=ROOT/'work'/'entry1s51_2024'/'tape'
    start=json.loads((H/'2024共同读取启动时刻.json').read_text(encoding='utf-8'))
    cutoff=float(start['preexisting_cutoff_unix']);assert cutoff<float(start['recorded_at_unix']);tasks=[]
    for (sym,day,n),g in d.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));prior=w51/(early.key_for(fp51,spec)+'.json');target=work/(r.key_for(fp,spec)+'.json')
        if prior.exists() and prior.stat().st_mtime<cutoff and not target.exists():tasks.append(spec)
    tasks.sort(key=lambda x:(max(index.get(e['observation_id'],{}).get('bytes',10**12) for e in x[3]),x[1],x[0]))
    manifest={'selected_stable_groups':len(tasks),'observation_ids':sorted(e['observation_id'] for s in tasks for e in s[3]),
              'note':'Only preexisting stable one-second checkpoints; unfinished dual-worker groups are excluded.'}
    (H/'2024旧逐笔补算任务清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_2024_STABLE_BACKFILL_TASKS',len(tasks),flush=True);r.direct.fetch=public_range.fetch;done=0;errors=[]
    for spec in tasks:
        if shutil.disk_usage(ROOT).free<2_200_000_000:break
        z=r.task(year,fp,spec,index,refs,work)
        if z['status']!='verified':
            errors.append({'contract':z['contract'],'day':z['day'],'error':z.get('error')})
            if 'headroom' in z.get('error',''):break
        done+=1
        if done%5==0:print('EXIT1R48_2024_STABLE_BACKFILL',done,'/',len(tasks),'errors',len(errors),flush=True)
    out={'processed_groups':done,'selected_groups':len(tasks),'errors':errors,'fingerprint':fp,
         'free_bytes':shutil.disk_usage(ROOT).free,'note':'Unfinished groups stay unknown and can be resumed.'}
    (H/'2024旧逐笔补算进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_2024_STABLE_BACKFILL_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
