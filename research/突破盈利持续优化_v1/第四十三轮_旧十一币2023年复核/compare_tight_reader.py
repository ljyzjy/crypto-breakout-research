"""Compare smaller-chunk replay against previously completed streaming events."""
import json,math
from pathlib import Path
import pandas as pd
import extract_old11_tapes as original
import stream_tapes_2023 as normal
import stream_tapes_2023_tight as tight
H=Path(__file__).resolve().parent
def same(a,b,path='root'):
    if isinstance(a,dict):
        assert isinstance(b,dict) and set(a)==set(b),path
        for k in a:same(a[k],b[k],path+'.'+str(k))
    elif isinstance(a,list):
        assert isinstance(b,list) and len(a)==len(b),path
        for i,(x,y) in enumerate(zip(a,b)):same(x,y,path+f'[{i}]')
    elif isinstance(a,float):assert isinstance(b,(int,float)) and math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-12),(path,a,b)
    else:assert a==b,(path,a,b)
def main():
    d=pd.read_parquet(original.SOURCE)
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]));chosen=[]
    for wanted in ('qualified','minute_trade_ohlc_mismatch'):
        for spec in tasks:
            f=normal.WORK/(normal.key_for(spec)+'.json')
            if not f.exists():continue
            prev=json.loads(f.read_text(encoding='utf-8'))
            if prev['status']=='verified' and any(r.get('status')==wanted for r in prev['rows']) and spec not in chosen:
                chosen.append(spec);break
    assert len(chosen)==2
    comparisons=[]
    for spec in chosen:
        prev=json.loads((normal.WORK/(normal.key_for(spec)+'.json')).read_text(encoding='utf-8'))
        new=tight.task(spec)
        assert new['status']=='verified',new
        same(prev,new)
        comparisons.append({'contract':spec[0],'day':spec[1],'rows':len(new['rows']),
                            'statuses':[r['status'] for r in new['rows']]})
        print('OLD11_TIGHT_READER_COMPARISON',len(comparisons),'/',len(chosen),flush=True)
    out={'all_fields_match':True,'normal_fp':normal.FP,'tight_fp':tight.FP,'original_fp':original.FP,
         'comparisons':comparisons,'note':'Same official archives and event paths; two independently refetched replay samples.'}
    (H/'小块读取一致性核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_TIGHT_READER_PASS',len(comparisons),flush=True)
if __name__=='__main__':main()
