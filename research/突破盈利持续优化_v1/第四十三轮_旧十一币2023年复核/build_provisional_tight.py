"""Snapshot completed 2023 tape checkpoints, keeping all pending candidates unknown."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
import extract_old11_tapes as source
import stream_tapes_2023 as stream
import stream_tapes_2023_tight as tight
H=Path(__file__).resolve().parent;O=H.parent/'第三十三轮_动态池逐笔执行';OUT=H/'部分批次';OUT.mkdir(exist_ok=True)
def main():
    d=pd.read_parquet(source.SOURCE);expected=set(d.observation_id);records={};used=0
    files=[(p,source.FP) for p in sorted(source.WORK.glob('*.json'))]+[(p,stream.FP) for p in sorted(stream.WORK.glob('*.json'))]+[(p,tight.FP) for p in sorted(tight.WORK.glob('*.json'))]
    for p,fp in files:
        z=json.loads(p.read_text(encoding='utf-8'))
        if z.get('status')!='verified':continue
        key=fp+'|'+z['contract']+'|'+z['day']+'|'+str(z['needs_next'])+'|'+'|'.join(sorted(x['observation_id'] for x in z['rows']))
        assert p.stem==hashlib.sha256(key.encode()).hexdigest()
        relevant=False
        for r in z['rows']:
            obs=r['observation_id']
            if obs not in expected:continue
            if obs in records:assert json.dumps(records[obs],sort_keys=True)==json.dumps(r,sort_keys=True)
            else:records[obs]=r
            relevant=True
        used+=int(relevant)
    missing=expected-set(records)
    for obs in sorted(missing):records[obs]={'observation_id':obs,'status':'archive_pending'}
    rows=[];paths=[]
    for obs,row in records.items():
        pre=row.get('prechecks',{})
        for variant,v in row.get('paths',{}).items():paths.append({'observation_id':obs,'variant':variant,**v})
        rows.append({**{k:v for k,v in row.items() if k not in ('paths','prechecks')},'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
    sig=pd.DataFrame(rows).merge(d,on='observation_id',validate='one_to_one',suffixes=('','_candidate'))
    p=pd.DataFrame(paths);assert not p.empty and not p.duplicated(['observation_id','variant']).any()
    sig.to_parquet(OUT/'动态池逐笔信号筛查.parquet',index=False);p.to_parquet(OUT/'动态池延迟市价路径.parquet',index=False)
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    meta={'candidate_events':len(d),'source_checkpoint_tasks':used,'pending_candidates':len(missing),
          'event_statuses':sig.status.value_counts().to_dict(),'unexpected_event_count':int((~sig.status.isin(benign)).sum()),
          'variant_paths':len(p),'unverified_path_count':int((~p.status.eq('verified')).sum()),
          'archive_errors':[{'status':'archive_pending','events':sorted(missing)}] if missing else [],
          'note':'Pending and data-disagreement events remain unknown. Snapshot is not a complete annual account.'}
    (OUT/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    rule={'source_plan_sha256':hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest(),
          'note':'See the frozen 2023 plan; execution and risk parameters are unchanged.'}
    (OUT/'逐笔执行冻结方案.json').write_text(json.dumps(rule,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copyfile(O/'不完整数据敏感性规则.json',OUT/'不完整数据敏感性规则.json')
    print('OLD11_2023_BATCH_PROVISIONAL',json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
