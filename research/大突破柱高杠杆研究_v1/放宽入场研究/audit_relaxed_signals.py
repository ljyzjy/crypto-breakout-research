"""Independent point-in-time signal checks and complete account reconciliation."""
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent.parent/'work'/'breakout_november_2026'
NORM=WORK/'normalized'
plan=json.loads((HERE.parent.parent/'突破胜率与净收益前瞻检验_v1'/'冻结研究方案.json').read_text(encoding='utf-8'))
pool=plan['fixed_pool'];mapping={x['symbol']:x['contract'] for x in pool};liq={x['symbol']:x['liquidity_rank'] for x in pool}
M=60_000;H=60*M;Q=15*M
WARM=int(pd.Timestamp('2026-04-01',tz='UTC').timestamp()*1000)

@lru_cache(maxsize=18)
def data(c):
    d=pd.read_parquet(NORM/f'{c}_klines.parquet').set_index('ts')
    assert d.index.is_unique
    return d

def bars(c,start,end):
    ix=np.arange(start,end,M,dtype=np.int64)
    d=data(c).reindex(ix)
    a=d[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float)
    o,h,l,cl,v,q,n=a.T
    valid=np.isfinite(a[:,:6]).all(axis=1)&(a[:,:6]>0).all(axis=1)
    valid&=(h>=np.maximum.reduce([o,l,cl]))&(l<=np.minimum.reduce([o,h,cl]))
    return a,valid

def reference(c,quarter,k,side):
    old,valid=bars(c,quarter-20*Q,quarter);cur,current_ok=bars(c,quarter,quarter+k*M)
    x=old.reshape(20,15,7);v=valid.reshape(20,15)
    assert v.all() and current_ok.all() and np.isfinite(x[:,:,6]).all() and (x[:,:,6]>0).all()
    assert np.isfinite(cur[:,6]).all() and (cur[:,6]>0).all()
    ratio=cur[:,6].sum()/x[:,:k,6].sum(axis=1).mean()
    upper=x[-16:,:,1].max();lower=x[-16:,:,2].min()
    assert ratio>=1.5 and (cur[-1,3]>upper if side==1 else cur[-1,3]<lower)

@lru_cache(maxsize=2048)
def hourly_stats(c,hour):
    # 25 fully completed hourly bars imply 24 returns.
    x,valid=bars(c,hour-25*H,hour)
    if len(x)!=25*60 or not valid.all():return None
    xx=x.reshape(25,60,7);closes=xx[:,-1,3]
    returns=np.diff(np.log(closes)); vol=np.std(returns,ddof=1)
    if not np.isfinite(vol) or vol<=0:return None
    score=float(returns[-6:].sum()/vol); current=float(xx[-1,:,5].sum());previous=[]
    for day in range(1,21):
        a,v=bars(c,hour-day*24*H-H,hour-day*24*H)
        if len(a)!=60 or not v.all():return None
        previous.append(float(a[:,5].sum()))
    den=float(np.median(previous))
    return (score,current/den) if den>0 else None

@lru_cache(maxsize=18)
def ema_direction(c):
    end=int(pd.Timestamp('2026-11-13',tz='UTC').timestamp()*1000)
    a,v=bars(c,WARM,end);q=a.reshape(-1,15,7);valid=v.reshape(-1,15).all(axis=1)
    close=pd.Series(np.where(valid,q[:,-1,3],np.nan))
    ema=close.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
    return np.select([close.gt(ema)&ema.gt(ema.shift()),close.lt(ema)&ema.lt(ema.shift())],[1,-1],0)


first=pd.read_parquet(HERE/'放宽候选与事后标签.parquet')
assert first.observation_id.is_unique
assert (first.decision_ts==first.break_ts+M).all() and (first.ts==first.decision_ts+M).all()
assert ((first.ts-first.quarter_start)<Q).all()
for symbol,g in first.sort_values('break_ts').groupby('symbol'):
    assert g.break_ts.diff().dropna().ge(60*M).all()
samples=first.iloc[np.linspace(0,len(first)-1,min(45,len(first)),dtype=int)]
for r in samples.itertuples(index=False):
    quarter=int(r.quarter_start);k=int((r.decision_ts-quarter)//M);side=int(r.side)
    past,valid=bars(r.contract,quarter-20*Q,quarter);cur,current_ok=bars(r.contract,quarter,quarter+k*M)
    assert valid.all() and current_ok.all()
    q=past.reshape(20,15,7);upper=float(q[-16:,:,1].max());lower=float(q[-16:,:,2].min())
    boundary=upper if side==1 else lower
    assert np.isclose(boundary,r.level,rtol=1e-10,atol=1e-10)
    assert side*(cur[-1,3]-boundary)>0
    if len(cur)>1:assert np.all((cur[:-1,3]<=upper)&(cur[:-1,3]>=lower))
    qhi=q[:,:,1].max(axis=1);qlo=q[:,:,2].min(axis=1);qcl=q[:,-1,3]
    tr=np.maximum.reduce([qhi[6:]-qlo[6:],abs(qhi[6:]-qcl[5:-1]),abs(qlo[6:]-qcl[5:-1])])
    atr=tr.mean();assert np.isclose(atr,r.atr,rtol=1e-10,atol=1e-10)
    stop=(cur[-1,2]-.1*atr) if side==1 else (cur[-1,1]+.1*atr)
    assert np.isclose(stop,r.stop_price,rtol=1e-10,atol=1e-10)
    ratio=cur[:,6].sum()/q[:,:k,6].sum(axis=1).mean()
    body=side*(cur[-1,3]-cur[0,0])/atr
    assert np.isclose(ratio,r.own_trade_count_ratio,rtol=1e-10,atol=1e-10) and ratio>=1.5
    assert np.isclose(body,r.partial_body_atr,rtol=1e-10,atol=1e-10) and body>=.25
    hour=int(r.decision_ts)//H*H;candidates=[]
    for item in pool:
        stat=hourly_stats(item['contract'],hour)
        if stat and stat[1]>=1.5 and stat[0]*side>0:
            candidates.append((item['symbol'],stat[0],stat[1],item['liquidity_rank']))
    candidates.sort(key=lambda x:(-abs(x[1]),x[3],x[0]))
    rank=next((i for i,x in enumerate(candidates[:3],1) if x[0]==r.symbol),None)
    assert rank==r.rank
    own=hourly_stats(r.contract,hour)
    assert own and np.isclose(own[0],r.score,rtol=1e-9,atol=1e-9) and np.isclose(own[1],r.rvol,rtol=1e-9,atol=1e-9)
    qi=(int(r.decision_ts)-WARM)//Q-1
    assert ema_direction(r.contract)[qi]==side
    major=all(ema_direction(mapping[s])[qi]==side for s in ['BTCUSDT','ETHUSDT'])
    assert bool(r.major_trend_pass)==major
    assert bool(r.early6_pass)==(r.ts-quarter<=6*M)
    complete,complete_ok=bars(r.contract,quarter,quarter+Q)
    assert complete_ok.all()
    final_body=side*(complete[-1,3]-complete[0,0])/complete[0,0];beyond=side*(complete[-1,3]-boundary)>0
    assert bool(r.large_1pct_label)==bool(final_body>=.01 and beyond)
    assert bool(r.large_halfpct_label)==bool(final_body>=.005 and beyond)
report={'all_candidate_timing_and_cooldowns_checked':len(first),'independently_reconstructed_sampled_signals':len(samples),'checks':['prior 16-bar boundary','first crossing','prior ATR and stop','own activity and partial body','hourly rank and relative volume','completed EMA trend of symbol/BTC/ETH','early entry and labels'],'limitation':'Deterministic sample shares underlying public bars and does not establish live fill quality.'}
(HERE/'放宽信号独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('RELAXED_SIGNAL_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
