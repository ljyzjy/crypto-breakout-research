import unittest
import numpy as np
import pandas as pd
from common import ROOT,read,dump,load_contract
from features import frame,enrich_hourly,signals_for,rank_hours,load_extended
from baseline_features import signals_for as old_signals

class Rules(unittest.TestCase):
    def bars(self,side=1):
        rows=[(60000,101.,101.5,100.5),(120000,100.4,100.8,100.3),(180000,100.1,100.4,99.9),(240000,100.8,101.,100.)]
        d=pd.DataFrame(rows,columns=['ts','close','high','low']);d['direction']=1;d['prior_high']=100.;d['prior_low']=98.
        d['atr']=1.;d['valid']=True;d['quote_volume']=1e6
        if side==-1:
            d[['close','high','low','prior_high','prior_low']]=pd.DataFrame({'close':200-d.close,'high':200-d.low,'low':200-d.high,'prior_high':200-d.prior_low,'prior_low':200-d.prior_high})
            d['direction']=-1
        return d
    def test_accept_touch_confirm_separate_both_sides(self):
        for side in [1,-1]:
            ranks={(0,'X',side):{'score':2*side,'rank':1,'rvol':2.}}
            d=self.bars(side);out,_=signals_for(d,ranks,'X','X',True)
            self.assertEqual(len(out),1)
            r=out.iloc[0];self.assertEqual((r.break_ts,r.accept_ts,r.touch_ts,r.ts),(60000,120000,180000,240000))
            self.assertAlmostEqual(r.stop_price,99.8 if side==1 else 100.2)
            self.assertTrue(signals_for(d.iloc[:3],ranks,'X','X',True)[0].empty)
    def test_immediate_band_touch_not_acceptance(self):
        d=self.bars();d.loc[1,'close']=100.1;d.loc[1,'low']=99.9
        out,_=signals_for(d,{(0,'X',1):{'score':2,'rank':1,'rvol':2}},'X','X',True)
        self.assertTrue(out.empty)
    def test_missing_or_lost_rank_resets_state(self):
        d=self.bars();d.loc[2,'valid']=False
        self.assertTrue(signals_for(d,{(0,'X',1):{'score':2,'rank':1,'rvol':2}},'X','X',True)[0].empty)
        self.assertTrue(signals_for(self.bars(),{},'X','X',True)[0].empty)
    def test_real_baseline_signal_equivalence(self):
        base=ROOT.parent/'pullback-intraday-no-daily-cap-v1'
        ranks=pd.read_parquet(base/'hourly-ranks.parquet')
        lookup={(r['hour'],r['symbol'],r['side']):r for r in ranks.to_dict('records')}
        for contract in ['BTCUSDT','ETHUSDT','1000PEPEUSDT']:
            match=ranks[ranks.contract.eq(contract)]
            if match.empty:continue
            symbol=match.symbol.iloc[0];raw=load_contract(contract,'klines');raw=raw[raw.index<'2025-02-02']
            d=frame(raw)[0];d=d[d.ts.ge(pd.Timestamp('2025-01-01',tz='UTC').value//10**6)]
            old=old_signals(d,lookup,symbol,contract)[0];new=signals_for(d,lookup,symbol,contract)[0]
            self.assertEqual(len(old),len(new))
            if len(old):pd.testing.assert_frame_equal(old.reset_index(drop=True),new[old.columns].reset_index(drop=True),check_dtype=False)
    def test_residual_ols_and_future_invariance(self):
        rng=np.random.default_rng(713);n=1000;ix=pd.date_range('2025-01-01',periods=n,freq='h',tz='UTC')
        br=rng.normal(0,.003,n);ar=.00001+1.7*br+rng.normal(0,.001,n)
        bc=pd.Series(100*np.exp(np.cumsum(br)),index=ix);ac=pd.Series(10*np.exp(np.cumsum(ar)),index=ix)
        h=pd.DataFrame({'close':ac,'quote_volume':6e7,'score':1.,'rvol':2.,'ts':ix.as_unit('ms').asi8})
        btc=pd.DataFrame({'close':bc});mi=pd.date_range(ix[0]-pd.Timedelta(hours=1),ix[-1],freq='min',inclusive='left')
        raw=pd.DataFrame({'open':10.,'high':11.,'low':9.,'close':10.,'volume':1e5,'quote_volume':1e6,'count':100,'taker_buy_quote_volume':5e5},index=mi)
        full=enrich_hourly(raw,h,btc);t=900
        rr=np.log(ac).diff();bb=np.log(bc).diff();x=bb.iloc[t-6-719:t-6+1].to_numpy();y=rr.iloc[t-6-719:t-6+1].to_numpy()
        alpha,beta=np.linalg.lstsq(np.c_[np.ones(720),x],y,rcond=None)[0]
        eps=rr.iloc[t-23:t+1].to_numpy()-alpha-beta*bb.iloc[t-23:t+1].to_numpy()
        score=eps[-6:].sum()/(eps.std(ddof=1)*np.sqrt(6))
        self.assertAlmostEqual(full.beta.iloc[t],beta,10);self.assertAlmostEqual(full.residual_score.iloc[t],score,10)
        part=enrich_hourly(raw[raw.index<ix[t]],h.iloc[:t+1],btc.iloc[:t+1])
        pd.testing.assert_frame_equal(full.iloc[:t+1],part)
        changed=h.copy();changed.loc[changed.index>ix[t],'close']*=100
        mutation=enrich_hourly(raw,changed,btc)
        pd.testing.assert_frame_equal(full.iloc[:t+1],mutation.iloc[:t+1])
        self.assertTrue(full.count_rvol.dropna().eq(1).all());self.assertTrue(full.active_quarters.dropna().eq(4).all())
    def test_rank_rules_and_btc_exclusion(self):
        rows=[dict(ts=1000,symbol=s,contract=c,score=score,residual_score=res,return6=own,rvol=2.,efficiency=eff,count_rvol=count,active_quarters=q,liquidity_rank=i+1,beta=1.,alpha=0.,residual6=res,taker_imbalance=0.,peak_quarter_share=.25) for i,(s,c,score,res,own,eff,count,q) in enumerate([('BTC','BTCUSDT',9,0,1,1,2,4),('A','AUSDT',6,2,1,.2,2,4),('B','BUSDT',3,3,1,1,2,4),('C','CUSDT',5,5,-1,1,2,4),('D','DUSDT',1,1,1,1,.5,1)])]
        d=pd.DataFrame(rows);cfg=read(ROOT/'protocol.json')['versions']
        r=rank_hours(d,cfg['residual']);self.assertEqual(r.symbol.tolist(),['B','A','D'])
        r=rank_hours(d,cfg['combined']);self.assertEqual(r.symbol.tolist(),['B','A'])
        prefix=rank_hours(pd.concat([d,d.assign(ts=2000,score=100)]),cfg['combined']);pd.testing.assert_frame_equal(r,prefix[prefix.hour.eq(1000)].reset_index(drop=True))

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Rules))
    dump(ROOT/'rule-validation.json',{'passed':result.wasSuccessful(),'tests':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'coverage':['long/short separate stages','fast baseline exact signal parity BTC/ETH/PEPE','OLS coefficient reference','feature prefix and future-price mutation','rank prefix and filter edges'],'limitations':'Finite checks, not universal proof of every future-information path.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)
