"""Reconstruct sampled old-period confirmation signals from the frozen minute data."""
import importlib.util,json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PREV=HERE.parent/'突破柱融合研究_v1'
P2=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase2')
spec=importlib.util.spec_from_file_location('old_audit_data',P2/'data_io.py');pio=importlib.util.module_from_spec(spec);spec.loader.exec_module(pio)
M=60_000;Q=15*M

def bars(c,start,end):
    d=pio.load_minutes(c,start,end).set_index('ts')
    ix=np.arange(start,end,M,dtype=np.int64)
    a=d.reindex(ix)[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float)
    o,h,l,cl,v,q,n=a.T
    valid=np.isfinite(a[:,:6]).all(axis=1)&(a[:,:6]>0).all(axis=1)
    valid&=(h>=np.maximum.reduce([o,l,cl]))&(l<=np.minimum.reduce([o,h,cl]))
    return a,valid

def ref(c,quarter,k,side):
    old,v=bars(c,quarter-20*Q,quarter);now,w=bars(c,quarter,quarter+k*M)
    x=old.reshape(20,15,7)
    assert v.all() and w.all() and np.isfinite(x[:,:,6]).all() and (x[:,:,6]>0).all() and (now[:,6]>0).all()
    ratio=now[:,6].sum()/x[:,:k,6].sum(axis=1).mean()
    bound=x[-16:,:,1].max() if side==1 else x[-16:,:,2].min()
    assert ratio>=1.5 and side*(now[-1,3]-bound)>0

first=pd.read_parquet(PREV/'signals.parquet');first=first[first.sync_pass]
confirm=pd.read_parquet(HERE/'历史确认信号.parquet')
paired=confirm.merge(first,on=['symbol','break_ts','side'],suffixes=('_confirm','_first'),validate='one_to_one',indicator=True)
assert paired._merge.eq('both').all() and (paired.decision_ts_confirm==paired.decision_ts_first+M).all()
sample=confirm.iloc[::max(1,len(confirm)//25)].head(25);mapping=pio.load_mapping()
for s in sample.itertuples(index=False):
    quarter=int(s.quarter_start);k=int((s.decision_ts-quarter)//M);side=int(s.side)
    assert s.ts==s.decision_ts+M and s.ts<quarter+Q
    source,valid=bars(s.contract,int(s.break_ts),int(s.break_ts)+2*M)
    assert valid.all() and side*(source[-1,3]-s.level)>0
    stop=float(source[:,2].min()-.1*s.atr if side==1 else source[:,1].max()+.1*s.atr)
    assert np.isclose(stop,s.stop_price,rtol=1e-10,atol=1e-10)
    for refsym in ['BTCUSDT','ETHUSDT']:ref(mapping[refsym],quarter,k,side)
result={'matched_first_events':len(paired),'independent_confirmation_signal_samples':len(sample),
        'checks':['two completed minutes','stop construction','entry timing','both references at confirmation'],
        'limits':'Sampled feature reconstruction, not full exchange execution verification.'}
(HERE/'历史确认信号抽样核对.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('HIST_CONFIRM_AUDIT_PASS',json.dumps(result,ensure_ascii=False),flush=True)
