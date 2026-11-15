"""Build fixed-entry 1R risk batches for frozen later periods."""
import hashlib,json,shutil,sys
from pathlib import Path
import pandas as pd
import run_1r_later as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(year):
    I=H/f'{year}冻结输入';OUT=H/f'{year}一倍止盈分批';f=json.loads((H/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    pub=P/'第四十七轮_一次重新突破确认'
    fp=hashlib.sha256((H/'run_1r_later.py').read_bytes()+(H/'冻结研究方案.md').read_bytes()+(H/f'{year}输入冻结哈希.json').read_bytes()+
                      (H/'exit_1r.py').read_bytes()+(pub/'public_tape_stream.py').read_bytes()).hexdigest()
    work=ROOT/'work'/f'exit1r48_{year}'/'tape';events=pd.read_parquet(I/'qualified_entries.parquet');refs=pd.read_parquet(I/'reference_2r_paths.parquet')
    a=pd.read_parquet(I/'baseline_signal.parquet');b=pd.read_parquet(I/'retry_signal.parquet')
    a=a[a.status.eq('qualified')].copy();a['entry_origin']='original';b=b[b.status.eq('qualified')].copy();b['entry_origin']='retest'
    cols=['observation_id','contract','side','source_year','decision_ts','quarter_end','precheck_10x','precheck_20x','entry_origin']
    signals=pd.concat([a[cols],b[cols]],ignore_index=True);assert signals.observation_id.is_unique and set(signals.observation_id)==set(events.observation_id)
    rows={};archives=[]
    for (symbol,day,needs),g in events.groupby(['contract','day','needs_next']):
        spec=(symbol,day,bool(needs),g.to_dict('records'));file=work/(runner.key_for(fp,spec)+'.json')
        if not file.exists():
            for obs in g.observation_id:rows[obs]={'status':'archive_pending'}
            continue
        z=json.loads(file.read_text(encoding='utf-8'));assert z['status']=='verified';archives.append({k:v for k,v in z.items() if k!='rows'})
        for row in z['rows']:assert row['observation_id'] not in rows;rows[row['observation_id']]=row
    assert set(rows)==set(events.observation_id);paths=[];statuses=[]
    for e in signals.to_dict('records'):
        obs=e['observation_id'];r=rows[obs];statuses.append({'observation_id':obs,'replay_status':r['status']})
        for lev in (10,20):
            if e[f'precheck_{lev}x']!='passed':continue
            variant=f'normal_1r_{lev}x';base=refs[(refs.observation_id==obs)&(refs.variant==f'normal_2r_{lev}x')]
            if len(base)!=1:result={'status':'missing_reference'}
            elif r['status']!='qualified':result={'status':r['status']}
            else:result=r.get('paths',{}).get(variant,{'status':'missing_replay'})
            paths.append({'observation_id':obs,'variant':variant,**result})
    signals=signals.merge(pd.DataFrame(statuses),on='observation_id',validate='one_to_one');paths=pd.DataFrame(paths)
    assert not paths.duplicated(['observation_id','variant']).any();OUT.mkdir(exist_ok=True)
    signals.to_parquet(OUT/'动态池逐笔信号筛查.parquet',index=False);paths.to_parquet(OUT/'动态池延迟市价路径.parquet',index=False)
    unknown=signals.loc[~signals.replay_status.eq('qualified'),'observation_id'].tolist()
    meta={'candidate_events':len(signals),'event_statuses':signals.replay_status.value_counts().to_dict(),
          'unexpected_event_count':len(unknown),'variant_paths':len(paths),'unverified_path_count':int((~paths.status.eq('verified')).sum()),
          'archive_errors':[{'status':'unresolved','events':unknown}] if unknown else [],'archives':archives,
          'note':'Only causally qualified frozen entries; missing 1R source or paths remain unknown.'}
    (OUT/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    src=P/'第四十六轮_固定十一加密币跨时段'/'逐笔冻结输入'/'old_execution_plan.json'
    metaold=json.loads((P/'第四十六轮_固定十一加密币跨时段'/'逐笔输入冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(src)==metaold['inputs']['old_execution_plan.json'];shutil.copyfile(src,OUT/'逐笔执行冻结方案.json')
    print('EXIT1R48_LATER_BATCH',year,json.dumps({k:v for k,v in meta.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
