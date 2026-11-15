"""One predeclared retest after the original five-second reference returned inside."""
import sys
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;ORIG=H.parent/'第三十三轮_动态池逐笔执行';sys.path.insert(0,str(ORIG))
from leveraged_paths import known_precheck,simulate_path,M
def fail(message):return {'status':'original_first_stage_disagreement','error':message}
def decide(e,tape):
    if e['status']!='flow_filter_not_met':return fail('original_status')
    side=int(e['side']);level=float(e['level']);qend=int(e['quarter_end']);minute=int(e['trigger_minute'])
    t=tape.transact_time.to_numpy(np.int64);p=tape.price.to_numpy(float)
    if not len(t) or np.any(t[1:]<t[:-1]) or not np.isfinite(p).all() or (p<=0).any():return fail('invalid_tape')
    ends=np.searchsorted(t,minute+M,side='left');cross=np.flatnonzero((p[:ends]>float(e['upper']))|(p[:ends]<float(e['lower'])))
    if not len(cross):return fail('first_cross_missing')
    first=int(cross[0]);first_side=1 if p[first]>float(e['upper']) else -1
    if first_side!=side or int(t[first])!=int(e['decision_ts']) or not np.isclose(p[first],e['signal_close'],rtol=1e-11,atol=1e-12):return fail('first_cross_changed')
    ref=int(np.searchsorted(t,int(t[first])+5_000,side='left'))
    if ref>=len(t) or int(t[ref])!=int(e['entry_exec_ts']) or not np.isclose(p[ref],e['raw_entry_5s'],rtol=1e-11,atol=1e-12):return fail('first_reference_changed')
    if side*(p[ref]-level)>0:return fail('first_reference_not_inside')
    window=tape[(tape.transact_time>int(t[first]))&(tape.transact_time<int(t[first])+5_000)]
    maker=window.is_buyer_maker.astype(str).str.lower();amount=window.price.to_numpy(float)*window.quantity.to_numpy(float)
    if len(window) and (not maker.isin(['true','false']).all() or not np.isfinite(amount).all() or (amount<=0).any()):return fail('first_flow_invalid')
    buy=float(amount[maker.eq('false').to_numpy()].sum());sell=float(amount[maker.eq('true').to_numpy()].sum())
    if len(window)!=int(e['five_count']) or not np.isclose(buy,e['buy_notional'],rtol=1e-9,atol=1e-8) or not np.isclose(sell,e['sell_notional'],rtol=1e-9,atol=1e-8):return fail('first_flow_changed')
    oldimb=e.get('five_imbalance');imb=side*(buy-sell)/(buy+sell) if buy+sell>0 else None
    if (pd.isna(oldimb) and imb is not None) or (not pd.isna(oldimb) and (imb is None or not np.isclose(imb,oldimb,rtol=1e-10,atol=1e-12))):return fail('first_imbalance_changed')
    possible=np.flatnonzero((np.arange(len(t))>ref)&(t<qend)&(side*(p-level)>0))
    if not len(possible):return {'status':'no_retest_known','side':side,'first_decision_ts':int(t[first])}
    ix=int(possible[0]);ts=int(t[ix]);raw=float(p[ix])
    if ts+5_000>=qend:return {'status':'no_order_time','side':side,'first_decision_ts':int(t[first]),'retest_ts':ts}
    ref2=int(np.searchsorted(t,ts+5_000,side='left'))
    if ref2>=len(t):return {'status':'missing_retest_reference','side':side,'retest_ts':ts}
    if int(t[ref2])>=qend:return {'status':'no_order_time','side':side,'first_decision_ts':int(t[first]),'retest_ts':ts}
    w=tape[(tape.transact_time>ts)&(tape.transact_time<ts+5_000)]
    mk=w.is_buyer_maker.astype(str).str.lower();v=w.price.to_numpy(float)*w.quantity.to_numpy(float)
    if len(w) and (not mk.isin(['true','false']).all() or not np.isfinite(v).all() or (v<=0).any()):return {'status':'invalid_retest_flow','side':side,'retest_ts':ts}
    b=float(v[mk.eq('false').to_numpy()].sum());s=float(v[mk.eq('true').to_numpy()].sum());imbalance=side*(b-s)/(b+s) if b+s>0 else None
    extra={'side':side,'first_decision_ts':int(t[first]),'retest_ts':ts,'decision_ts':ts,'signal_close':raw,
           'entry_exec_ts':int(t[ref2]),'raw_entry_5s':float(p[ref2]),'five_count':len(w),'buy_notional':b,'sell_notional':s,'five_imbalance':imbalance,
           'stop_price':float(e['stop_price']),'level':level}
    if len(w)<3 or imbalance is None or imbalance<.10 or side*(float(p[ref2])-level)<=0:return {'status':'retest_flow_filter_not_met',**extra}
    event={**e,**extra,'trigger_minute':ts//M*M};prechecks={str(lev):known_precheck(event,lev) or 'passed' for lev in (10,20)}
    paths={}
    for lev in (10,20):
        if prechecks[str(lev)]=='passed':paths[f'normal_2r_{lev}x']=simulate_path(event,tape.iloc[ix:],lev,False)
    return {'status':'qualified' if paths else 'known_risk_rejected',**extra,'prechecks':prechecks,'paths':paths}
