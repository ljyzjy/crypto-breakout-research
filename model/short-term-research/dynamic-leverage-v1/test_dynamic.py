import hashlib,json
import numpy as np
import pandas as pd
import dynamic_engine as e

def fixture():
    ix=pd.date_range('2025-01-01','2025-01-05',freq='5min',inclusive='left',tz='UTC');n=len(ix);px={};mk={}
    price=np.where(ix<pd.Timestamp('2025-01-02',tz='UTC'),100.,101.)
    price[287]=101.
    for s in e.SYMBOLS:
        px[s]=np.column_stack([price,price*1.001,price*.999,price,np.full(n,100.)]);mk[s]=px[s][:,:4].copy()
    z=dict(index=ix,px=px,mk=mk,rates={s:np.zeros(n) for s in e.SYMBOLS},ok={s:np.ones(n,bool) for s in e.SYMBOLS},avail={s:np.ones(n,int) for s in e.SYMBOLS},mom={s:np.ones(n,int) for s in e.SYMBOLS},budgets={'BTCUSDT':np.full(n,50.),'ETHUSDT':np.zeros(n)},decision=np.array(ix.minute==0))
    f={s:pd.DataFrame({'sigma5':.01,'sigma20':.02,'vol_median120':.03,'one_day_return':.01,'mom10':.05,'mom30':.1,'mom60':.15,'known_funding24':0.},index=pd.date_range('2025-01-01','2025-01-04',tz='UTC')) for s in e.SYMBOLS}
    return z,f

def main():
    checks=[]
    z,f=fixture();r=e.simulate('2025-01-01','2025-01-04','tiered',fixture=z,feature_fixture=f)
    adds=[o for o in r['orders'] if o['reason']=='leverage_add'];assert len(adds)==8 and all(o['ts']==1735776000 for o in adds)
    assert all(o['core_age_hours']>=24 and o['core_net_unrealized']>0 and o['stop_risk_pct']<=2 for o in adds)
    assert r['ledger_error']<1e-8 and r['boost_trades']==8 and r['core_trades']==1
    # Downshift the entire ladder;one-day cooldown prevents immediate re-add.
    f['BTCUSDT'].loc['2025-01-03','sigma5']=.04
    down=e.simulate('2025-01-01','2025-01-04','tiered',fixture=z,feature_fixture=f)
    assert len([o for o in down['orders'] if o['reason']=='daily_regime_reduce'])==8
    assert all(o['ts']>=1735948800 for o in down['orders'] if o['reason']=='leverage_add' and o['ts']>1735776000)
    # Last24h funding cannot qualify a fivefold ceiling when costly for held side.
    row={k:float(v) for k,v in f['BTCUSDT'].iloc[0].items()};row['known_funding24']=.001
    assert e.regime(row,1,'tiered')[0]==1.5 and e.regime(row,-1,'tiered')[0]==1.5
    row.update(mom10=-.05,mom30=-.1,mom60=-.15);assert e.regime(row,-1,'tiered')[0]==5
    z2,f2=fixture();z2['px']['BTCUSDT'][287,3]=99.;z2['mk']['BTCUSDT'][287,3]=99.
    no=e.simulate('2025-01-01','2025-01-04','tiered',fixture=z2,feature_fixture=f2)
    assert not any(o['reason']=='leverage_add' and o['ts']==1735776000 for o in no['orders'])
    checks.append('Half-lot ladder up to5x,24hprofitablecore gate,aggregate stop-risk2percent,regime reduction/cooldown,funding-sideconditions verified')
    for mode,L,fee,delay in [('fixed1',1,.001,0),('fixed2',2,.001,0),('fixed5',5,.001,0),('fixed2',2,.003,0),('fixed1',1,.001,5)]:
        a=e.simulate('2025-01-01','2026-10-31',mode,fee,delay);b=e.prior.cached_run('2025-01-01','2026-10-31','momentum_ls',L,fee,delay)
        for k in ('return_pct','max_drawdown','fees','slippage_cost','funding_cost','mean_exposure_pct'):assert abs(a[k]-b[k])<1e-7,(mode,k,a[k],b[k])
        assert a['core_trades']==b['trade_count']
        print('baseline',mode,fee,delay,'passed',flush=True)
    checks.append('Five control paths exactly reproduce previous1x/2x/5xlongshort economics,fees,funding,DD and delayedexecution')
    raw=e.prior.old.prior.old.daily();fund={s:e.prior.old.load_frame('perp',s,'fundingRate') for s in e.SYMBOLS};allf=e.features()
    for end in ('2025-06-30','2026-06-30'):
        cut=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1);f=e.features_from_daily(raw.loc[raw.date<cut],{s:d.loc[d.index<cut] for s,d in fund.items()})
        for s in e.SYMBOLS:pd.testing.assert_frame_equal(f[s],allf[s].loc[f[s].index])
    checks.append('Dailyvolatility/trend/funding factors unchanged by two future truncations;fundingatdecisionboundaryexcluded')
    e.base.dump(e.ROOT/'preflight.json',dict(passed=True,checks=checks))
    frozen={'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in e.ROOT.glob('*.py')},'protocol':hashlib.sha256((e.ROOT/'protocol.json').read_bytes()).hexdigest(),'perp_manifest':hashlib.sha256((e.prior.old.ROOT/'data-manifest.json').read_bytes()).hexdigest(),'daily_manifest':hashlib.sha256((e.prior.old.prior.old.ROOT/'pool-data-manifest.json').read_bytes()).hexdigest()}
    e.base.dump(e.ROOT/'frozen.json',frozen);print(json.dumps({'passed':True,'checks':checks}))
if __name__=='__main__':main()
