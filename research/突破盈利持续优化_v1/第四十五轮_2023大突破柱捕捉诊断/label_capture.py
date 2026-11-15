"""Rebuild post-close large-candle labels from frozen local minute data."""
import hashlib,json
from decimal import Decimal
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';M=60_000;Q=15*M
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    frozen=json.loads((H/'冻结输入哈希.json').read_text(encoding='utf-8'))
    assert sha(H/'事后诊断方案.md')==frozen['plan_sha256']
    for n,v in frozen['inputs'].items():assert sha(I/n)==v
    src=json.loads((I/'minute_hashes.json').read_text(encoding='utf-8'))['sources']
    events=pd.read_parquet(I/'candidates.parquet');assert events.observation_id.is_unique
    result=[]
    for symbol,g in events.groupby('contract',sort=True):
        item=src[f'{symbol}_klines.parquet'];file=Path(item['path']);assert sha(file)==item['sha256']
        d=pd.read_parquet(file,columns=['ts','open','high','low','close','volume','trade_count'])
        assert d.ts.is_unique;d=d.set_index('ts')
        for e in g.to_dict('records'):
            q=int(e['quarter_start']);x=d.reindex(range(q-16*Q,q+Q,M))
            row={'observation_id':e['observation_id'],'contract':symbol,'quarter_start':q,'status':'unknown',
                 'allowed_side':int(e['market_allowed_side']),'large':None}
            a=x[['open','high','low','close','volume','trade_count']].to_numpy(float)
            if len(x)!=255 or not np.isfinite(a).all() or not (a[:,:4]>0).all() or not (a[:,4:]>0).all():
                row['reason']='missing_or_nonpositive_minute';result.append(row);continue
            if (a[:,1]<np.maximum.reduce([a[:,0],a[:,2],a[:,3]])).any() or (a[:,2]>np.minimum.reduce([a[:,0],a[:,1],a[:,3]])).any():
                row['reason']='invalid_minute_ohlc';result.append(row);continue
            hi=float(a[:-15,1].max());lo=float(a[:-15,2].min())
            if not np.isclose(hi,e['upper'],rtol=1e-9,atol=1e-12) or not np.isclose(lo,e['lower'],rtol=1e-9,atol=1e-12):
                row['reason']='prior_boundary_mismatch';row['rebuilt_upper']=hi;row['rebuilt_lower']=lo;result.append(row);continue
            op=float(a[-15,0]);high=float(a[-15:,1].max());low=float(a[-15:,2].min());close=float(a[-1,3])
            side=row['allowed_side'];assert side in (-1,1) and e['market_prior_status']=='allowed'
            assert bool(e['long_known_eligible'] if side==1 else e['short_known_eligible'])
            change=Decimal(side)*(Decimal(str(close))-Decimal(str(op)))/Decimal(str(op))
            boundary=Decimal(str(hi if side==1 else lo))
            beyond=(Decimal(side)*(Decimal(str(close))-boundary)>0)
            row.update({'status':'verified','reason':'ok','open':op,'high':high,'low':low,'close':close,
                        'volume':float(a[-15:,4].sum()),'trade_count':int(a[-15:,5].sum()),
                        'rebuilt_upper':hi,'rebuilt_lower':lo,'large':bool(change>=Decimal('0.01') and beyond)})
            result.append(row)
        del d
    labels=pd.DataFrame(result);assert labels.observation_id.is_unique and len(labels)==len(events)
    labels.to_parquet(H/'2023候选事后大柱标签.parquet',index=False)
    out={'candidate_count':len(labels),'label_statuses':labels.status.value_counts().to_dict(),
         'unknown_reasons':labels.loc[labels.status.ne('verified'),'reason'].value_counts().to_dict(),
         'label_sha256':sha(H/'2023候选事后大柱标签.parquet'),
         'note':'Close-based labels are descriptive and were not known at entry.'}
    (H/'事后标签质量.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE45_LABEL_QUALITY',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
