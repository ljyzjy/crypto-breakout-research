import json,hashlib
import numpy as np
import pandas as pd
import factor_engine as e

def fixture(direction=-1,rate=0.,high=100.1,ending=99.):
    ix=pd.date_range('2025-01-01','2025-01-02',inclusive='left',freq='5min',tz='UTC');n=len(ix)
    px={s:np.tile([100.,high,99.,ending,100.],(n,1)) for s in e.SYMBOLS}
    mk={s:np.tile([100.,high,99.,ending],(n,1)) for s in e.SYMBOLS}
    rates={s:np.zeros(n) for s in e.SYMBOLS};rates['BTCUSDT'][96]=rate
    return dict(index=ix,px=px,mk=mk,rates=rates,ok={s:np.ones(n,bool) for s in e.SYMBOLS},avail={s:np.ones(n,int) for s in e.SYMBOLS},signals={s:np.zeros(n,int) for s in e.SYMBOLS},mom={s:np.full(n,direction,int) for s in e.SYMBOLS},budgets={'BTCUSDT':np.full(n,100.),'ETHUSDT':np.zeros(n)},decision=np.array(ix.minute==0))

def main():
    checks=[]
    r=e.simulate('2025-01-01','2025-01-01','momentum_ls',fixture=fixture())
    assert r['valid_for_comparison'] and r['short_pnl']>0 and r['long_trades']==0 and r['ledger_error']<1e-8
    t=r['trades'][0];assert t['entry_price']<100 and t['exit_price']>99
    pos=e.simulate('2025-01-01','2025-01-01','momentum_ls',fixture=fixture(rate=.001))
    neg=e.simulate('2025-01-01','2025-01-01','momentum_ls',fixture=fixture(rate=-.001))
    assert pos['funding_cost']<0 and neg['funding_cost']>0
    z=fixture();z['rates']['BTCUSDT'][0]=.001
    assert e.simulate('2025-01-01','2025-01-01','momentum_ls',fixture=z)['funding_cost']==0
    z['rates']['BTCUSDT'][0]=-.001
    assert e.simulate('2025-01-01','2025-01-01','momentum_ls',fixture=z)['funding_cost']>0
    r=e.simulate('2025-01-01','2025-01-01','momentum_ls',10,fixture=fixture(high=105.))
    assert not r['valid_for_comparison'] and r['return_pct'] is None and r['data_issues'][0]['kind']=='collateral_stress_intrabar'
    checks.append('Short price profit,adverse entry/exit slippage,funding sign,boundary no-credit and markHIGH stress verified')
    ix=pd.date_range('2024-12-01',periods=40*12,freq='5min',tz='UTC');d=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':1.},index=ix)
    d.loc[ix[5*12:6*12],'low']=98.;d.loc[ix[30*12:31*12],'low']=97. # oldlow outside24 window => newesttouch matters
    d.loc[ix[10*12:11*12],'high']=103.;d.loc[ix[30*12:31*12],'high']=104.
    f=e.sweep_factors(d);assert f.loc[pd.Timestamp('2024-12-02 07:00',tz='UTC'),'direction']==-1
    # Positive signal: unique old low remains within prior24 and aged>=6.
    d.loc[ix[10*12:11*12],'low']=98.;d.loc[ix[30*12:31*12],'high']=101.
    f=e.sweep_factors(d);assert f.loc[pd.Timestamp('2024-12-02 07:00',tz='UTC'),'direction']==1
    for cutoff in ('2025-06-30 23:55','2026-06-30 23:55'):
        for s in e.SYMBOLS:
            raw=e.old.load_frame('perp',s,'klines');ts=pd.Timestamp(cutoff,tz='UTC');prefix=e.sweep_factors(raw.loc[:ts]);full=e.all_factors()[s].loc[prefix.index]
            pd.testing.assert_frame_equal(prefix,full)
    checks.append('Synthetic old extreme/age/sweep and actual-data future truncation preserve factors')
    for L,fee,delay in ((1,.001,0),(2,.001,0),(2,.003,0),(2,.001,5)):
        r=e.simulate('2025-01-01','2026-10-31','long_control',L,fee,delay)
        o=e.old.cached_run('2025-01-01','2026-10-31','btc_eth','perp',L,fee,delay)
        for k in ('return_pct','max_drawdown','fees','slippage_cost','funding_cost'):
            assert abs(r[k]-o[k])<1e-7,(L,fee,delay,k,r[k],o[k])
        assert r['trade_count']==o['trade_count']
    checks.append('Four long-only full-period controls exactly reproduce prior economics')
    frozen={'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in e.ROOT.glob('*.py')},'protocol':hashlib.sha256((e.ROOT/'protocol.json').read_bytes()).hexdigest(),'data_manifest':hashlib.sha256((e.old.ROOT/'data-manifest.json').read_bytes()).hexdigest()}
    e.base.dump(e.ROOT/'frozen.json',frozen);e.base.dump(e.ROOT/'preflight.json',{'passed':True,'checks':checks});print(json.dumps({'passed':True,'checks':checks}))
if __name__=='__main__':main()
