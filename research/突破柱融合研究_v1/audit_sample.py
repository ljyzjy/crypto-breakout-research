"""Independent sampled reconstruction from minute records; read-only inputs."""
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
P2=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase2')
spec=importlib.util.spec_from_file_location('audit_phase2',P2/'data_io.py')
pio=importlib.util.module_from_spec(spec); spec.loader.exec_module(pio)
M=60_000; Q=15*M

def minutes(contract, start, end):
    d=pio.load_minutes(contract, start, end).set_index('ts')
    ix=np.arange(start,end,M,dtype=np.int64)
    d=d.reindex(ix)
    a=d[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float)
    o,h,l,c,v,q,n=a.T
    valid=np.isfinite(a[:,:6]).all(axis=1)&(a[:,:6]>0).all(axis=1)
    valid&=(h>=np.maximum.reduce([o,l,c]))&(l<=np.minimum.reduce([o,h,c]))
    return a,valid

def reconstruct(contract, quarter, k):
    # The current prefix ends at the decision, never at the future quarter end.
    past, pv=minutes(contract,quarter-20*Q,quarter)
    cur, cv=minutes(contract,quarter,quarter+k*M)
    assert len(past)==300 and len(cur)==k
    p=past.reshape(20,15,7); valid=pv.reshape(20,15)
    cts=p[:,:,6]
    good=valid.all() and np.isfinite(cts).all() and (cts>0).all()
    curgood=cv.all() and np.isfinite(cur[:,6]).all() and (cur[:,6]>0).all()
    ratio=float(cur[:,6].sum()/cts[:,:k].sum(axis=1).mean()) if good and curgood else np.nan
    hi=float(p[-16:,:,1].max()) if valid[-16:].all() else np.nan
    lo=float(p[-16:,:,2].min()) if valid[-16:].all() else np.nan
    return ratio,hi,lo,cur

def main():
    sig=pd.read_parquet(HERE/'signals.parquet')
    mapping=pio.load_mapping()
    groups=[sig.head(2),sig.tail(2),sig[sig.activity_pass].head(4),sig[~sig.activity_pass].head(4),
            sig[sig.sync_pass].tail(4),sig.sort_values('ts').iloc[::max(1,len(sig)//12)].head(12)]
    sample=pd.concat(groups).drop_duplicates('observation_id')
    checked=[]
    for r in sample.itertuples(index=False):
        quarter=int(r.quarter_start); k=int((int(r.decision_ts)-quarter)//M)
        assert 1<=k<=13 and int(r.ts)<quarter+Q
        _,upper,lower,cur=reconstruct(r.contract,quarter,k)
        boundary=upper if r.side==1 else lower
        assert np.isclose(boundary,r.level,rtol=1e-10,atol=1e-10)
        assert r.side*(cur[-1,3]-boundary)>0
        if k>1:
            assert np.all((cur[:-1,3]<=upper)&(cur[:-1,3]>=lower))
        ratios=[]; dirs=[]
        for symbol in ['BTCUSDT','ETHUSDT']:
            ratio, hi, lo, prefix=reconstruct(mapping[symbol],quarter,k)
            ratios.append(ratio)
            dirs.append(prefix[-1,3]>hi if r.side==1 else prefix[-1,3]<lo)
        assert np.isclose(ratios[0],r.btc_ratio,rtol=1e-10,atol=1e-10,equal_nan=True)
        assert np.isclose(ratios[1],r.eth_ratio,rtol=1e-10,atol=1e-10,equal_nan=True)
        active=all(np.isfinite(x) and x>=1.5 for x in ratios)
        assert bool(r.activity_pass)==active
        assert bool(r.sync_pass)==bool(active and all(dirs))
        checked.append({'id':r.observation_id,'elapsed_minutes':k,'activity':active,'sync':bool(r.sync_pass)})
    result={'sample_count':len(checked),'independent_minute_reconstruction_passed':True,
            'scope':'sampled signals only; no claim of full independent accounting audit','samples':checked}
    (HERE/'sample_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SAMPLE_AUDIT_PASS',len(checked))

if __name__=='__main__':main()
