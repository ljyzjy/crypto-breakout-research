"""Pre-result causality/accounting/constraint tests with deterministic fixtures."""
import json
import pandas as pd
import numpy as np
import rotation_engine as e

def fixture(stop=False,funding=0.,marklow=99.):
    ix=pd.date_range('2025-01-01','2025-01-12',inclusive='left',freq='5min',tz='UTC');symbols=('BTCUSDT','ETHUSDT')
    px={s:np.tile([100.,99.,100.,100.],(len(ix),1)) for s in symbols};mk={s:np.tile([100.,marklow,100.],(len(ix),1)) for s in symbols}
    if stop:px['BTCUSDT'][0,1]=95.
    rates={s:np.zeros(len(ix)) for s in symbols};rates['BTCUSDT'][0]=funding
    ok={s:np.ones(len(ix),dtype=bool) for s in symbols};trace={};known={}
    for d in pd.date_range('2025-01-01','2025-01-11',tz='UTC'):
        ts=int(d.timestamp());trace[ts]={'date':d.strftime('%Y-%m-%d'),'information_through':(d-pd.Timedelta(days=1)).strftime('%Y-%m-%d'),'ranked':[{'symbol':'BTCUSDT'},{'symbol':'ETHUSDT'}],'daily_top2':['BTCUSDT','ETHUSDT']};known[ts]={s:(True,100.) for s in symbols}
    return symbols,ix,px,mk,rates,ok,{s:v.copy() for s,v in ok.items()},trace,known

def main():
    ranks=[{'symbol':s} for s in ('A','B','C','D','E')]
    assert e.retained_selection(ranks,{'C':{},'D':{}})==['C','D']
    assert e.retained_selection(ranks,{'E':{},'C':{}})==['C','A']
    assert e.retained_selection(ranks,{})==['A','B']
    checks=['Buffer retains only actual positions within qualifiedtop4, fills fromtop2, maximum2']
    a=e.simulate('2025-01-01','2025-01-11','slow_base',fixture=fixture(True));b=e.simulate('2025-01-01','2025-01-11','delayed_retry',fixture=fixture(True))
    buy=lambda r:[pd.Timestamp(o['ts'],unit='s',tz='UTC').strftime('%Y-%m-%d') for o in r['orders'] if o['side']=='buy' and o['symbol']=='BTCUSDT']
    assert buy(a)==['2025-01-01','2025-01-02'] and buy(b)==['2025-01-01','2025-01-06']
    assert len([o for o in a['orders'] if o['side']=='buy' and o['ts']==1735689600])==2
    checks.append('Same-open entries precede stoplow recognition; nextMonday retry works')
    c=e.simulate('2025-01-01','2025-01-11','slow_base','perp',2,fixture=fixture(funding=.001))
    assert c['valid_for_comparison'] and c['funding_cost']>0 and c['ledger_error']<1e-8
    assert abs(c['trades'][0]['notional']-200)<1e-9 and c['trades'][0]['margin']==100
    neg=e.simulate('2025-01-01','2025-01-11','slow_base','perp',2,fixture=fixture(funding=-.001))
    assert neg['funding_cost']==0,'No credit for new exactboundary entry'
    earned=fixture();earned[4]['BTCUSDT'][96]=-.001
    credit=e.simulate('2025-01-01','2025-01-11','slow_base','perp',2,fixture=earned)
    assert credit['funding_cost']<0 and credit['ledger_error']<1e-8
    low=e.simulate('2025-01-01','2025-01-11','slow_base','perp',10,fixture=fixture(marklow=95.))
    assert not low['valid_for_comparison'] and low['halted'] and low['return_pct'] is None and low['annualized_return_pct'] is None
    missing=fixture();missing[5]['BTCUSDT'][0]=False
    bad=e.simulate('2025-01-01','2025-01-11','slow_base','perp',1,fixture=missing)
    assert not bad['valid_for_comparison']
    checks.append('Perpetual margin,notional,positive funding cost,boundarynegative credit,ledger and collateral/coverage halt verified')
    # Known baseline only; no new candidate outcomes are inspected during preflight.
    r=e.simulate('2025-01-01','2026-10-31','slow_base')
    old=e.prior.cached_run('2025-01-01','2026-10-31','pool_slow_selection')
    for field in ('return_pct','max_drawdown','fees','slippage_cost','mean_exposure_pct'):
        assert abs(r[field]-old[field])<1e-8,(field,r[field],old[field])
    assert len(r['orders'])==len(old['orders'])
    for x,y in zip(r['orders'],old['orders']):
        for field in ('side','symbol','ts','reason','information_ts'):assert x[field]==y[field],field
        assert abs(x['cash']-y['cash'])<1e-8
    btc=e.simulate('2025-01-01','2026-10-31','btc_eth')
    oldbtc=e.prior.old.c.cached_run('2025-01-01','2026-10-31','vol_target200',.001,'5m',0,('BTCUSDT','ETHUSDT'))
    for field in ('return_pct','max_drawdown','fees','slippage_cost','mean_exposure_pct'):assert abs(btc[field]-oldbtc[field])<1e-8,(field,btc[field],oldbtc[field])
    checks.append('Actual full-period slowbaseline andBTCETH2U reproduce existing economic results andbaselineorder chronology')
    e.base.dump(e.ROOT/'preflight-validation.json',{'passed':True,'checks':checks});print(json.dumps({'passed':True,'checks':checks}))

if __name__=='__main__':main()
