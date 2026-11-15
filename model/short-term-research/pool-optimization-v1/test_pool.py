import json
from types import FunctionType,SimpleNamespace
import pandas as pd
import numpy as np
import pool_engine as p

def synthetic(mode,stop=.04,stake=100,dual=False):
    index=pd.date_range('2025-01-01','2025-01-12',inclusive='left',freq='h',tz='UTC');source=index-pd.Timedelta(hours=1)
    symbols=('AAA','BBB') if dual else ('AAA',)
    raw={};frames={};budgets={};distances={}
    for s in symbols:
        d=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':100.},index=index)
        d.loc[index[0],'low']=95. if stop==.04 else 88.
        raw[(s,'1h')]=d
        frames[s]=pd.DataFrame({'DailyMomentum_buy':source.hour==23,'DailyMomentum_sell':False},index=source)
        budgets[s]=pd.Series(stake,index=source);distances[s]=pd.Series(stop,index=source)
    scope=dict(p.execution.simulate_path.__globals__)
    scope.update(SYMBOLS=symbols,POLICIES=p.VARIANTS,sizing_frames=lambda d,m:budgets)
    runner=FunctionType(p.execution.simulate_path.__code__,scope,'test_execution',p.execution.simulate_path.__defaults__)
    return runner('2025-01-01','2025-01-11',mode,.001,'1h',0,raw,frames,False,distances)

def slow_with(frame):
    factors=p.old.rank_history(frame)
    proxy=SimpleNamespace(daily=lambda:frame,rankings=lambda:factors)
    fn=p.slow_rankings.__wrapped__;scope=dict(fn.__globals__);scope['old']=proxy
    return FunctionType(fn.__code__,scope,'private_slow_rankings')()

def main():
    checks=[]
    a=synthetic('pool_control');b=synthetic('pool_weekly_retry')
    buys=lambda r:[pd.Timestamp(o['ts'],unit='s',tz='UTC').strftime('%Y-%m-%d') for o in r['orders'] if o['side']=='buy']
    assert buys(a)==['2025-01-01','2025-01-02'],buys(a)
    assert buys(b)==['2025-01-01','2025-01-06'],buys(b)
    checks.append('Stop recognition blocks retry until next Monday; original cooldown control unchanged')
    d=synthetic('pool_vol_stop',.10,40)
    assert d['trades'][0]['reason']=='stop_loss' and abs(d['trades'][0]['planned_stop_loss']-4)<1e-9
    assert abs(d['trades'][0]['exit_reference']-100.05*.9)<1e-9
    x=synthetic('pool_control',dual=True)
    assert len([o for o in x['orders'] if o['side']=='buy' and o['ts']==1735689600])==2
    checks.append('Volatility stop/4U planned risk consistent; current-bar low cannot prevent other same-open entry')
    frame=p.old.daily();cut=pd.Timestamp('2025-06-30',tz='UTC')
    prefix=slow_with(frame[frame.date<cut]);full=p.slow_rankings()
    assert prefix==[r for r in full if r['date']<='2025-06-30']
    changed=frame.copy();changed.loc[changed.date>=cut,['open','high','low','close','volume','quote_volume']]*=8
    assert prefix==[r for r in slow_with(changed) if r['date']<='2025-06-30']
    checks.append('Slow selection full-universe future mutation and prefix invariance')
    for mode in p.VARIANTS:
        syms,frames,budgets,stops,trace=p.prepare('2025-01-01','2026-10-31',mode)
        for s in syms:
            buy=frames[s].DailyMomentum_buy
            assert all(t.hour==23 for t in frames[s].index[buy])
            assert budgets[s].between(0,200).all()
            assert stops[s].between(.04,.20).all()
            if p.VARIANTS[mode]['volstop']:
                assert ((budgets[s]*stops[s])<=4+1e-9).all()
        if p.VARIANTS[mode]['gate']:
            assert all(not any(frames[s].loc[pd.Timestamp(r['date'],tz='UTC')-pd.Timedelta(hours=1),'DailyMomentum_buy'] for s in syms) for r in trace if not r['market_allows_entry'])
    checks.append('All6 specifications use closed-day information,200Ucaps and prescribed risk/market conditions')
    p.old.base.dump(p.ROOT/'preflight-validation.json',{'passed':True,'checks':checks})
    print(json.dumps({'passed':True,'checks':checks}))

if __name__=='__main__':main()
