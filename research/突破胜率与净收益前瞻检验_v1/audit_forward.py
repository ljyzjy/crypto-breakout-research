"""Independent point-in-time signal checks and complete account reconciliation."""
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_forward_2026'
NORM=WORK/'normalized'
plan=json.loads((HERE/'冻结研究方案.json').read_text(encoding='utf-8'))
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
    end=int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000)
    a,v=bars(c,WARM,end);q=a.reshape(-1,15,7);valid=v.reshape(-1,15).all(axis=1)
    close=pd.Series(np.where(valid,q[:,-1,3],np.nan))
    ema=close.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
    return np.select([close.gt(ema)&ema.gt(ema.shift()),close.lt(ema)&ema.lt(ema.shift())],[1,-1],0)

first=pd.read_parquet(HERE/'first_signals.parquet');confirm=pd.read_parquet(HERE/'confirmed_signals.parquet')
assert first.observation_id.is_unique and confirm.observation_id.is_unique
keycols=['symbol','break_ts','side']
paired=confirm.merge(first,on=keycols,how='left',suffixes=('_confirm','_first'),validate='one_to_one',indicator=True)
assert paired._merge.eq('both').all() and (paired.decision_ts_confirm==paired.decision_ts_first+M).all()
samples=pd.concat([first.iloc[::max(1,len(first)//15)].head(15),confirm.iloc[::max(1,len(confirm)//15)].head(15)],ignore_index=True)
for r in samples.itertuples(index=False):
    quarter=int(r.quarter_start);k=int((r.decision_ts-quarter)//M);side=int(r.side)
    assert 1<=k<=13 and int(r.ts)==int(r.decision_ts)+M and r.ts<quarter+Q
    past,valid=bars(r.contract,quarter-20*Q,quarter);cur,current_ok=bars(r.contract,quarter,quarter+k*M)
    assert valid.all() and current_ok.all()
    q=past.reshape(20,15,7);upper=float(q[-16:,:,1].max());lower=float(q[-16:,:,2].min())
    boundary=upper if side==1 else lower
    assert np.isclose(boundary,r.level,rtol=1e-10,atol=1e-10)
    cross_i=int((r.break_ts-quarter)//M)
    assert side*(cur[cross_i,3]-boundary)>0 and side*(cur[-1,3]-boundary)>0
    if cross_i:assert np.all((cur[:cross_i,3]<=upper)&(cur[:cross_i,3]>=lower))
    qhi=q[:,:,1].max(axis=1);qlo=q[:,:,2].min(axis=1);qcl=q[:,-1,3]
    tr=np.maximum.reduce([qhi[6:]-qlo[6:],abs(qhi[6:]-qcl[5:-1]),abs(qlo[6:]-qcl[5:-1])])
    atr=tr.mean();assert np.isclose(atr,r.atr,rtol=1e-10,atol=1e-10)
    src=cur[cross_i:] if r.observation_id.startswith('confirm|') else cur[cross_i:cross_i+1]
    stop=(src[:,2].min()-.1*atr) if side==1 else (src[:,1].max()+.1*atr)
    assert np.isclose(stop,r.stop_price,rtol=1e-10,atol=1e-10)
    for s in ['BTCUSDT','ETHUSDT']:reference(mapping[s],quarter,k,side)
    hour=int(r.decision_ts)//H*H;candidates=[]
    for item in pool:
        stat=hourly_stats(item['contract'],hour)
        if stat and stat[1]>=1.5 and stat[0]*side>0:
            candidates.append((item['symbol'],stat[0],stat[1],item['liquidity_rank']))
    candidates.sort(key=lambda x:(-abs(x[1]),x[3],x[0]))
    rank=next((i for i,x in enumerate(candidates[:3],1) if x[0]==r.symbol),None)
    assert rank==r.rank
    own=hourly_stats(r.contract,hour);assert own and np.isclose(own[0],r.score,rtol=1e-9,atol=1e-9) and np.isclose(own[1],r.rvol,rtol=1e-9,atol=1e-9)
    qi=(int(r.decision_ts)-WARM)//Q-1
    assert ema_direction(r.contract)[qi]==side

all_results=json.loads((HERE/'全部账户结果.json').read_text(encoding='utf-8'))
assert len(all_results)==36
max_dd_error=0.;max_ledger_error=0.
for sm in all_results:
    stem=f"{sm['period']}_{sm['run_id']}_{sm['scenario']}"
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(WORK/f'{stem}_curve.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes']
    assert len(trades)==len(entries)==sm['trades']
    eq=np.r_[1000.,curve.equity.to_numpy()]
    dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    max_dd_error=max(max_dd_error,abs(dd-sm['max_drawdown']))
    max_ledger_error=max(max_ledger_error,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(f['actual_charge'] for f in funding))<1e-7
    for t in trades:
        side=1 if t['side']=='long' else -1
        expected=t['entry']+side*sm['target_r']*side*(t['entry']-t['stop'])
        assert np.isclose(expected,t['target'],rtol=1e-10,atol=1e-10)
    if sm['scenario']=='main':assert sm['entered_within_original_quarter']==sm['trades']
assert max_dd_error<1e-8 and max_ledger_error<1e-6
report={'sampled_signal_count':len(samples),'confirmation_parent_checks':len(paired),
 'signal_checks':['prior16 boundary','previous14 ATR','first crossing','both BTC/ETH activity and direction','hourly rank and relative volume','prior 15m EMA direction','stop','decision/entry time'],
 'accounts_reconciled':len(all_results),'max_dd_error_pct_points':max_dd_error,'max_ledger_error':max_ledger_error,
 'limitations':'Independent sampled signal reconstruction and accounting checks; historical archive and minute execution remain common to both implementations.'}
(HERE/'独立抽样与账户对账.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('FORWARD_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
