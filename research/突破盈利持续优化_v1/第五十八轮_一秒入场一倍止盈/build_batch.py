"""Build a resumable 1s/1R batch without treating pending groups as trades."""
import json,shutil,sys
from pathlib import Path
import pandas as pd
import run_early_1r as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;FAST=P/'第五十一轮_缩短市价入场延迟'
sys.path.insert(0,str(FAST));import run_entry_1s as previous
def main(year):
    events,refs=runner.sources(year);fp=runner.fingerprint(year);fp51=previous.fingerprint(year)
    old=ROOT/'work'/f'entry1s51_{year}'/'tape';work=ROOT/'work'/f'early1r58_{year}'/'tape';I=H/f'{year}冻结输入';OUT=H/f'{year}一秒一倍分批';OUT.mkdir(exist_ok=True)
    rows={};archives=[]
    for (sym,day,n),g in events.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));prior=old/(previous.key_for(fp51,spec)+'.json')
        if not prior.exists():
            for obs in g.observation_id:rows[obs]={'status':'prior_checkpoint_missing'}
            continue
        cp=work/(runner.key(fp,spec,runner.sha(prior))+'.json')
        if not cp.exists():
            for obs in g.observation_id:rows[obs]={'status':'archive_pending'}
            continue
        z=json.loads(cp.read_text(encoding='utf-8'));assert z['status']=='verified' and z['upstream_checkpoint_sha256']==runner.sha(prior)
        archives.append({k:v for k,v in z.items() if k!='rows'})
        for row in z['rows']:assert row['observation_id'] not in rows;rows[row['observation_id']]=row
    assert set(rows)==set(events.observation_id)
    signal=pd.read_parquet(I/'signal.parquet');assert signal.observation_id.is_unique and set(signal.observation_id)==set(events.observation_id)
    signal=signal.drop(columns=['replay_status'],errors='ignore');signal['replay_status']=signal.observation_id.map(lambda x:rows[x]['status'])
    paths=[]
    for oldpath in refs.to_dict('records'):
        obs=oldpath['observation_id'];r=rows[obs];variant=oldpath['variant'].replace('one_second_2r_','one_second_1r_')
        result=r.get('paths',{}).get(variant,{'status':r['status'] if r['status']!='qualified' else 'missing_path'})
        paths.append({'observation_id':obs,'variant':variant,**result})
    paths=pd.DataFrame(paths);assert not paths.duplicated(['observation_id','variant']).any()
    signal.to_parquet(OUT/'动态池逐笔信号筛查.parquet',index=False);paths.to_parquet(OUT/'动态池延迟市价路径.parquet',index=False)
    unknown=signal.loc[~signal.replay_status.eq('qualified'),'observation_id'].tolist()
    quality={'candidate_events':len(signal),'event_statuses':signal.replay_status.value_counts().to_dict(),
             'unexpected_event_count':len(unknown),'variant_paths':len(paths),'unverified_path_count':int((~paths.status.eq('verified')).sum()),
             'archive_errors':[{'status':'unresolved','events':unknown}] if unknown else [],'archives':archives,
             'note':'Pending 1R groups remain unknown; same previously verified one-second entries.'}
    (OUT/'动态池逐笔提取质量.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(I/'execution.json',OUT/'逐笔执行冻结方案.json')
    print('EARLY1R58_BATCH',year,json.dumps({k:v for k,v in quality.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
