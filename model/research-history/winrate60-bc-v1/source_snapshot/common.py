from pathlib import Path
import sys, json, hashlib, importlib.util
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parents[2]
OUT=BASE/'outputs/winrate60-bc-v1'
P3=BASE/'outputs/feature-research-phase3'
P2=BASE/'outputs/feature-research-phase2'
sys.path.insert(0,str(P3/'account'))
from market_io import load_minutes,load_mark,load_funding,load_mapping,load_quarantine,get_manifest
from account_market import RankTrendGuard,Market,load_symbol_hourly
from engine import simulate
M=60000;H=3600000;D=86400000
def ms(x):return int(pd.Timestamp(x,tz='UTC').timestamp()*1000)
LO=ms('2025-01-01');TRAIN_END=ms('2025-04-01');CAL_END=ms('2025-07-01');END=ms('2026-04-27')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')
def save(name,d):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);d.to_parquet(p,index=False)
def freeze_check():
    reg=read(OUT/'registration.json');assert sha(OUT/'protocol.json')==reg['protocol_sha256']
    pro=read(OUT/'protocol.json');assert sha(P3/'account/market_manifest.json')==pro['data']['market_manifest_sha256']
    return pro
PROTOCOL=freeze_check();FEATURES=PROTOCOL['features']
def phase2_io():
    spec=importlib.util.spec_from_file_location('win60_phase2_data',P2/'data_io.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
def valid_bars(a):
    return (np.isfinite(a[:,:6]).all(axis=1)&(a[:,:6]>0).all(axis=1)&
      (a[:,1]>=np.max(a[:,[0,2,3]],axis=1))&(a[:,2]<=np.min(a[:,[0,1,3]],axis=1)))
def hourly(symbol,contract):
    h=load_symbol_hourly(symbol,contract,['ts','r6','residual6','vol24','quote_rvol','hourly_return']).set_index('ts')
    h=h.reindex(np.arange(h.index.min(),h.index.max()+H,H))
    h['r24']=h.hourly_return.rolling(24,min_periods=24).sum()
    return h
def span(times,a,start,end):
    l=np.searchsorted(times,start);r=np.searchsorted(times,end)
    if r-l!=(end-start)//M or not np.array_equal(times[l:r],np.arange(start,end,M)):return None
    return a[l:r]
def feature_vector(s,times,a,h,bh):
    t=int(s['decision_ts']);side=int(s['side']);A=float(s['atr']);B=float(s['level']);key=t//H*H
    w=span(times,a,int(s['break_ts']),t);flow=span(times,a,t-3*M,t)
    if w is None or flow is None or not valid_bars(w).all() or not valid_bars(flow).all():return None
    if key not in h.index or key not in bh.index:return None
    row=h.loc[key];btc=bh.loc[key];close=float(w[-1,3]);frac=side*(close-s['stop_price'])/close
    if not (np.isfinite(flow[:,7]).all() and ((flow[:,7]>=0)&(flow[:,7]<=flow[:,5])).all()):return None
    high=np.maximum(side*w[:,1],side*w[:,2]);low=np.minimum(side*w[:,1],side*w[:,2]);peak=high.max();last=int(np.flatnonzero(high==peak)[-1]);recovery=0.
    if last<len(w)-1:
        trough=low[last+1:].min()
        if peak>trough:recovery=float(np.clip((side*close-trough)/(peak-trough),0,1))
    residual=float(side*row.residual6)
    with np.errstate(divide='ignore',invalid='ignore'):
        f={'aligned_r6':float(side*row.r6/(np.sqrt(6)*row.vol24)),
          'aligned_r24':float(side*row.r24/(np.sqrt(24)*row.vol24)),
          'aligned_btc24':float(side*btc.r24/(np.sqrt(24)*btc.vol24)),
          'aligned_residual6':residual,'residual_missing':float(not np.isfinite(residual)),
          'is_btc':float(s['symbol']=='BTCUSDT'),'boundary_distance':side*(close-B)/A,
          'outside_fraction':float(np.mean(side*(w[1:,3]-B)>=.25*A)),
          'drawdown_atr':float((peak-side*close)/A),'recovery_fraction':recovery,
          'taker_imbalance3':float(side*(2*flow[:,7].sum()-flow[:,5].sum())/flow[:,5].sum()),
          'price_change3_atr':float(side*(flow[-1,3]-flow[0,0])/A),'stop_cost_ratio':.002/frac,
          'log_quote_rvol':float(np.log1p(row.quote_rvol)),'atr_fraction':A/close,'side_feature':float(side)}
    if not all(np.isfinite(f[k]) for k in FEATURES if k!='aligned_residual6'):return None
    return f

