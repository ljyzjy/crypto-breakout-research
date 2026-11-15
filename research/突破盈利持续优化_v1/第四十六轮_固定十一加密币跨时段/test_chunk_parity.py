"""Check small-block features against the previously frozen full-array algorithm."""
import json,math,shutil,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import minute_features_fixed11 as full
from chunk_exact import derive_chunked
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent
def same(a,b,path='root'):
    if isinstance(a,dict):
        assert isinstance(b,dict) and set(a)==set(b),path
        for k in a:same(a[k],b[k],path+'.'+str(k))
    elif isinstance(a,(float,np.floating)):
        assert math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-12),(path,a,b)
    else:assert a==b,(path,a,b)
def test_case(year,sym,start,end):
    while psutil.virtual_memory().available<350*1024**2:
        if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
        time.sleep(3)
    folder='breakout_2024_11' if year==2024 else 'breakout_forward_2026'
    source=ROOT/'work'/folder/'normalized'/f'{sym}_klines.parquet'
    d=pd.read_parquet(source,columns=['ts','open','high','low','close','volume','quote_volume','trade_count'])
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000);hi=int(pd.Timestamp(end,tz='UTC').timestamp()*1000)
    d=d[d.ts.between(lo,hi-1)];grid=np.arange(lo,hi,60_000,dtype=np.int64);a=np.full((len(grid),7),np.nan)
    idx=((d.ts.to_numpy(np.int64)-lo)//60_000).astype(int);assert len(np.unique(idx))==len(idx)
    a[idx]=d[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float);del d
    dates=pd.to_datetime(grid[::1440],unit='ms',utc=True).strftime('%Y-%m-%d');pool=set(dates)
    ha,ea,_=full.derive(a,grid,sym,year,pool);hb,eb,_=derive_chunked(a,grid,sym,year,pool)
    pd.testing.assert_frame_equal(ha.reset_index(drop=True),hb.reset_index(drop=True),check_exact=False,rtol=1e-9,atol=1e-12)
    left={x['observation_id']:x for x in ea};right={x['observation_id']:x for x in eb};assert set(left)==set(right)
    for obs in left:
        x=dict(left[obs]);y=dict(right[obs])
        for k in ('long_spec','short_spec'):x[k]=json.loads(x[k]);y[k]=json.loads(y[k])
        same(x,y,obs)
    return {'year':year,'contract':sym,'start':start,'end':end,'hours_checked':len(ha),'candidate_events_checked':len(left)}
def main():
    frozen=json.loads((H/'来源冻结哈希.json').read_text(encoding='utf-8'))
    # Two fixed, pre-outcome periods and different coins; no returns are read.
    cases=[(2024,'BTCUSDT','2023-12-01','2024-02-01'),(2026,'NEARUSDT','2026-04-01','2026-06-01')]
    checks=[]
    for case in cases:
        checks.append(test_case(*case));print('FIXED11_46_CHUNK_PARITY',len(checks),'/',len(cases),flush=True)
    assert sum(x['candidate_events_checked'] for x in checks)>0
    out={'all_checks_pass':True,'cases':checks,
         'note':'Hourly rows, causal candidate IDs and all candidate fields match full-array algorithm on two fixed real-data slices.'}
    (H/'小块算法一致性核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_CHUNK_PARITY_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
