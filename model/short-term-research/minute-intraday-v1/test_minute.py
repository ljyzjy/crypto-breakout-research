"""Economic and causal tests; executable with unittest, no downloaded data required."""
import unittest
import numpy as np
import pandas as pd
from features import make_features
from engine import simulate,MINUTE

START=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
BASE={'id':'fixture','fee':.0005,'slippage':.0005,'delay_minutes':0}

def signals(side=1,times=None):
    return pd.DataFrame([{'ts':t,'side':side,'symbol':'TESTUSDT','contract':'TESTUSDT',
       'signal_close':100.,'atr':1.,'previous_quote_volume':1e7,'source_open_ts':t-MINUTE,
       'hour':START,'score':3.*side,'rank':1} for t in (times or [START+MINUTE])])

class FixtureMarket:
    def __init__(self,overrides=None,funding=None,missing=None):
        self.overrides=overrides or {};self.funding={'TESTUSDT':funding or {}};self.missing=missing
    def change_month(self,ts):pass
    def bar(self,c,ts,mark=False):
        if ts==self.missing:return None
        a=np.array(self.overrides.get(ts,[100.,100.1,99.9,100.,1e5,1e7]),float)
        return a[:4] if mark else a
    def funding_ok(self,c,ts):return True

class MinuteTests(unittest.TestCase):
    def run_case(self,market=None,side=1,times=None,scenario=None):
        return simulate(scenario or BASE,signals(side,times),'2025-01-01','2025-01-01',market or FixtureMarket(),False)
    def test_long_short_cost_and_ledger(self):
        for side in (1,-1):
            r,curve,trades,orders=self.run_case(side=side)
            self.assertTrue(r['valid_for_comparison']);self.assertEqual(len(trades),1)
            self.assertLess(trades[0]['net'],0);self.assertAlmostEqual(r['ledger_error'],0,places=8)
            self.assertEqual(trades[0]['holding_minutes'],60)
            self.assertLessEqual(orders[0]['notional'],500)
            self.assertLessEqual(orders[0]['planned_loss'],orders[0]['known_equity']*.0025+1e-8)
    def test_ambiguous_stop_is_first(self):
        t=START+2*MINUTE
        r,_,trades,_=self.run_case(FixtureMarket({t:[100.,105.,95.,100.,1e5,1e7]}))
        self.assertTrue(r['valid_for_comparison']);self.assertEqual(trades[0]['reason'],'stop')
        self.assertTrue(trades[0]['ambiguous']);self.assertLess(trades[0]['net'],0)
    def test_missing_held_bar_invalidates(self):
        r,*_=self.run_case(FixtureMarket(missing=START+2*MINUTE))
        self.assertFalse(r['valid_for_comparison']);self.assertIn('missing',r['issues'][0])
    def test_signed_funding(self):
        t=START+10*MINUTE
        market=FixtureMarket(funding={t:[(t,.001)]})
        long,*_=self.run_case(market,1);short,*_=self.run_case(market,-1)
        self.assertGreater(long['funding_cost'],0);self.assertLess(short['funding_cost'],0)
    def test_entry_minute_no_funding_credit(self):
        t=START+MINUTE
        r,*_=self.run_case(FixtureMarket(funding={t:[(t,.001)]}),-1)
        self.assertEqual(r['funding_cost'],0)
    def test_cooldown_and_no_same_exit_refill(self):
        t=START+2*MINUTE
        r,_,trades,orders=self.run_case(FixtureMarket({t:[100.,105.,95.,100.,1e5,1e7]}),
            times=[START+MINUTE,START+3*MINUTE,START+4*MINUTE,START+65*MINUTE])
        self.assertEqual(len(orders),2);self.assertEqual(orders[-1]['ts'],START+65*MINUTE)
        self.assertGreater(r['rejection_counts'].get('symbol_cooldown',0),0)
    def test_delay_and_late_day(self):
        sc={**BASE,'delay_minutes':1}
        _,_,_,orders=self.run_case(scenario=sc)
        self.assertEqual(orders[0]['ts'],orders[0]['signal_ts']+MINUTE)
        r,_,_,orders=self.run_case(times=[START+14*60*MINUTE])
        self.assertEqual(orders,[]);self.assertEqual(r['rejection_counts']['late_day'],1)
    def test_day_close(self):
        #21:59 Beijing entry exits at22:59 due maximum60min, never after23:55.
        r,_,trades,_=self.run_case(times=[START+(13*60+59)*MINUTE])
        self.assertEqual(trades[0]['reason'],'time60')
        self.assertLessEqual((trades[0]['exit_ts']//MINUTE+480)%1440,1435)
    def test_feature_prefix(self):
        ix=pd.date_range('2024-12-28',periods=6000,freq='min',tz='UTC')
        rng=np.random.default_rng(23);close=100*np.exp(np.cumsum(rng.normal(.00002,.001,len(ix))))
        raw=pd.DataFrame({'open':close,'high':close*1.001,'low':close*.999,'close':close,
                          'volume':1000.,'quote_volume':rng.uniform(1e5,5e5,len(ix))},index=ix)
        full,h=make_features(raw)
        for cutoff in (3000,4377):
            short,hs=make_features(raw.iloc[:cutoff]);when=int((ix[cutoff-1]+pd.Timedelta(minutes=1)).timestamp()*1000)
            pd.testing.assert_frame_equal(full[full.ts<=when].reset_index(drop=True),short.reset_index(drop=True))
            pd.testing.assert_frame_equal(h[h.ts<=when].reset_index(drop=True),hs[hs.ts<=when].reset_index(drop=True))
    def test_order_prefix(self):
        signal=signals(times=[START+MINUTE,START+120*MINUTE])
        _,_,_,full=simulate(BASE,signal,'2025-01-01','2025-01-02',FixtureMarket(),False)
        _,_,_,short=simulate(BASE,signal,'2025-01-01','2025-01-01',FixtureMarket(),False)
        self.assertEqual([o for o in full if o['ts']<START+86400000],short)

if __name__=='__main__':unittest.main(verbosity=2)
