"""Accounting, causal universe and frozen-engine regression checks."""
import json,hashlib
import pandas as pd
import numpy as np
import coin_engine as c
import automatic_engine as a

def run():
    checks=[]
    r=c.enrich({'start':'2025-01-01','end':'2026-12-31','initial':1000,'final_equity':1210,'return_pct':21})
    assert r['elapsed_days']==730 and abs(r['annualized_return_pct']-10)<1e-10
    assert c.enrich({'start':'2026-01-01','end':'2026-10-31','return_pct':50})['annualized_return_pct'] is None
    assert c.enrich({'start':'2025-01-01','end':'2026-10-31','return_pct':50,'valid_for_comparison':False})['annualized_return_pct'] is None
    checks.append('CAGR compound/account/inclusive-day/short-period/invalid-path cases')
    original=c.base.cached_run('2025-01-01','2026-10-31','DailyMomentum',.001,'5m',0)
    adapted=c.cached_run('2025-01-01','2026-10-31','fixed100',.001,'5m',0)
    for field in ('trades','orders','curve','return_pct','max_drawdown','cash_min','fees','slippage_cost'):
        assert original[field]==adapted[field],field
    checks.append('BTC+ETH adapter reproduces frozen original 5m ledger and curve exactly')
    r=c.cached_run('2025-01-01','2025-03-31','fixed100',.001,'5m',0,('BTCUSDT',))
    assert all(t['symbol']=='BTCUSDT' for t in r['orders']) and r['ledger_error']<1e-7
    checks.append('Single-coin replay excludes other coin and reconciles cash')
    for r in c.base.read(c.ROOT/'sizing-metrics.json'):
        assert r['cash_min']>=0 and r['ledger_error']<1e-7 and not r['data_issues']
        d=c.base.read(c.ROOT/'results'/(r['id']+'.json.gz'))
        budget=c.sizes(c.inputs(('BTCUSDT','ETHUSDT'))[0],r['mode'],('BTCUSDT','ETHUSDT'))
        for t in d['trades']:
            info=pd.Timestamp(t['entry_ts']-r['delay_minutes']*60-3600,unit='s',tz='UTC')
            if r['mode']!='inverse_vol_pair':assert abs(t['stake']-float(budget[t['symbol']].loc[info]))<1e-8
        assert all(o['information_ts']<=o['ts'] for o in d['orders'] if o['information_ts'] is not None)
    checks.append('All49 sizing scenarios: past-only budget lookup, cash and trade-ledger checks')
    frame=a.daily();_,trace,excluded=a.rankings();cut=pd.Timestamp('2025-06-30',tz='UTC')
    modified=frame.copy();future=modified.date>=cut
    modified.loc[future,['open','high','low','close','volume','quote_volume']]*=7
    _,mutated,_=a.rank_history(modified)
    expected=[r for r in trace if r['date']<='2025-06-30']
    assert expected==[r for r in mutated if r['date']<='2025-06-30']
    _,prefix,_=a.rank_history(frame[frame.date<cut])
    assert expected==prefix
    checks.append('Entire archive-universe prefix and future-price/volume mutation invariance')
    assert 'JUPUSDT' not in excluded and 'USDCUSDT' in excluded
    fixture=frame[frame.symbol=='BTCUSDT'].copy()
    _,_,leveraged=a.rank_history(pd.concat([fixture.assign(symbol='BTCUPUSDT'),fixture.assign(symbol='BTCDOWNUSDT')]))
    assert 'BTCUPUSDT' in leveraged and 'BTCDOWNUSDT' in leveraged
    for r in trace:
        assert len(r['pool'])<=20 and len(r['daily_top2'])<=2
        assert all(p['median_volume']>=10_000_000 for p in r['pool'])
        assert all(p['momentum']>0 for p in r['ranked'])
    for start,end in [('2025-01-01','2025-07-20'),('2026-01-01','2026-10-31')]:
        symbols,frames,budgets,selected=a.prepare(start,end,'auto_budget3')
        for s,f in frames.items():
            assert all(t.hour==23 for t in f.index[f.DailyMomentum_buy|f.DailyMomentum_sell])
            assert budgets[s].max()<=300 and budgets[s].min()>=0
        for i,r in enumerate(selected):
            if i and pd.Timestamp(r['date']).weekday()!=0:assert r['selected']==selected[i-1]['selected']
    checks.append('Stable/leveraged exclusion without JUP false positive; weekly freeze, top20/top2 and closed-day sizing')
    c.base.dump(c.ROOT/'validation.json',{'passed':True,'checks':checks})
    print(json.dumps({'passed':True,'checks':checks},ensure_ascii=False),flush=True)

if __name__=='__main__':run()
