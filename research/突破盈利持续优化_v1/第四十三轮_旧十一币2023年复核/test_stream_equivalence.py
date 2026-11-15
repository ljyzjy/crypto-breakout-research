"""Replay two completed archives through the streaming reader and compare all fields."""
import json,math
from pathlib import Path
import pandas as pd
import stream_tapes_2023 as stream
import extract_old11_tapes as orig
H=Path(__file__).resolve().parent;W=orig.ROOT/'work'/'old11_2023_dual'/'stream_test';W.mkdir(parents=True,exist_ok=True)
def equal(a,b,path='root'):
    if isinstance(a,dict) and isinstance(b,dict):
        assert set(a)==set(b),(path,'keys')
        for k in a:equal(a[k],b[k],path+'.'+k)
    elif isinstance(a,list) and isinstance(b,list):
        assert len(a)==len(b),(path,'len')
        for i,(x,y) in enumerate(zip(a,b)):equal(x,y,f'{path}[{i}]')
    elif isinstance(a,(int,float)) and isinstance(b,(int,float)) and not isinstance(a,bool) and not isinstance(b,bool):
        assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-10),(path,a,b)
    else:assert a==b,(path,a,b)
def main():
    d=pd.read_parquet(orig.SOURCE);available=[]
    for p in orig.WORK.glob('*.json'):
        z=json.loads(p.read_text(encoding='utf-8'))
        if z.get('status')=='verified':available.append(z)
    chosen=[]
    for target in ('qualified','minute_trade_ohlc_mismatch'):
        matches=[r for r in available if any(x['status']==target for x in r['rows']) and r not in chosen]
        if not matches:raise ValueError('missing_overlap_sample_'+target)
        chosen.append(min(matches,key=lambda r:sum(x['bytes'] for x in r['archives'])))
    results=[]
    for old in chosen:
        group=d[(d.contract==old['contract'])&(d.day==old['day'])&(d.needs_next==old['needs_next'])]
        spec=(old['contract'],old['day'],bool(old['needs_next']),group.to_dict('records'))
        assert {x['observation_id'] for x in old['rows']}==set(group.observation_id)
        new=stream.task(spec,work=W);assert new['status']=='verified',new
        a={**old,'rows':sorted(old['rows'],key=lambda x:x['observation_id'])}
        b={**new,'rows':sorted(new['rows'],key=lambda x:x['observation_id'])}
        equal(a,b)
        results.append({'contract':old['contract'],'day':old['day'],'events':len(old['rows']),
                        'statuses':[x['status'] for x in old['rows']]})
        print('OLD11_2023_STREAM_SAMPLE',len(results),'/2',flush=True)
    out={'independent_overlap_groups':len(results),'samples':results,'all_fields_match':True,
         'original_fp':orig.FP,'stream_fp':stream.FP,
         'note':'Two sample groups only; production remains separately fingerprinted and disagreements must remain unknown.'}
    (H/'流式读取一致性核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_STREAM_EQUIVALENCE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
