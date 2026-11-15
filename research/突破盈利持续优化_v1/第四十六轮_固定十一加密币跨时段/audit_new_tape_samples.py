"""Independently replay four newly downloaded fixed-pool trade paths."""
import hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;I=H/'逐笔冻结输入'
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as direct
sys.path.insert(0,str(P/'第四十三轮_旧十一币2023年复核'));from audit_2023_tape_samples import replay
import stream_fixed11_tapes as stream
def main():
    check=json.loads((P/'第四十七轮_一次重新突破确认'/'无落盘逐笔读取真实样本核验.json').read_text(encoding='utf-8'))
    assert check['all_checks_pass'] and check['stream_code_sha256']==hashlib.sha256((P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest()
    plan=pd.read_parquet(H/'逐笔复用计划.parquet').set_index('observation_id')
    c=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True).set_index('observation_id')
    available=[]
    for file in sorted(stream.WORK.glob('*.json')):
        rec=json.loads(file.read_text(encoding='utf-8'))
        if rec.get('status')!='verified':continue
        for row in rec['rows']:
            obs=row['observation_id']
            if obs not in plan.index or plan.loc[obs,'reuse_status']!='need_new_tape' or row.get('status')!='qualified':continue
            if not all(v['status']=='verified' for v in row['paths'].values()):continue
            available.append((rec,row))
    chosen=[]
    for year in ('2024','2026'):
      for side in (1,-1):
        candidates=[x for x in available if str(c.loc[x[1]['observation_id'],'source_year'])==year and int(x[1]['side'])==side]
        if candidates:chosen.append(sorted(candidates,key=lambda x:x[1]['observation_id'])[0])
    for x in available:
        if len(chosen)>=4:break
        if x[1]['observation_id'] not in [z[1]['observation_id'] for z in chosen]:chosen.append(x)
    assert len(chosen)==4
    samples=[]
    for rec,row in chosen:
        obs=row['observation_id'];e={**c.loc[obs].to_dict(),**{k:v for k,v in row.items() if k not in ('paths','prechecks')}};e['observation_id']=obs
        body,bar=stream.engine.archive('klines',e['contract'],e['day']);del body
        assert bar['sha256']==next(x['sha256'] for x in rec['archives'] if x['kind']=='klines')
        blocks=[];archives=[]
        for a in (x for x in rec['archives'] if x['kind']=='aggTrades'):
            got,meta=direct.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60_000)})
            assert meta['sha256']==a['sha256'];blocks.extend(got[obs]);archives.append(meta)
        tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        for variant,path in row['paths'].items():
            lev=int(variant.rsplit('_',1)[1].rstrip('x'));actual=replay(e,tape,lev,variant.startswith('fast_'))
            for key,value in actual.items():
                if isinstance(value,float):assert np.isclose(value,path[key],rtol=1e-11,atol=1e-12),(obs,variant,key)
                else:assert value==path[key],(obs,variant,key)
        samples.append({'observation_id':obs,'year':str(e['source_year']),'side':int(e['side']),
                        'paths_checked':len(row['paths']),'archives':archives})
        print('FIXED11_46_NEW_TAPE_SAMPLE',len(samples),'/4',flush=True)
    out={'all_checks_pass':True,'samples':samples,'paths_checked':sum(x['paths_checked'] for x in samples),
         'note':'Independent replay of public prints, not actual order execution.'}
    (H/'新增逐笔样本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_NEW_TAPE_AUDIT_PASS',len(samples),flush=True)
if __name__=='__main__':main()
