"""Synthetic-only tests; safe to run before any real outcome is opened."""
import unittest
import numpy as np
import pandas as pd
from methods import *

class TestMethods(unittest.TestCase):
    def fixture(self,n=100):
        rng=np.random.default_rng(42)
        d=pd.DataFrame({c:rng.normal(size=n) for c in ['r6','btc_r6','residual6','vol24','efficiency6','concentration6','rv_relative60','range_atr','boundary_distance','outside_fraction5','drawdown_atr','recovery_fraction','utc_hour_sin','utc_hour_cos']})
        d['quote_rvol']=rng.uniform(.1,5,n); d['count_rvol']=rng.uniform(.1,5,n)
        d['side']=rng.choice([-1,1],n); d['symbol']=rng.choice(['A','B'],n)
        return d

    def test_fit_only_training_future_mutation_does_not_change_prediction(self):
        train=self.fixture(); y=2*train.r6*train.side+3*train.residual6*train.side
        m=fit_ols(train,y,BASE+GROUPS['F1'])
        future=self.fixture(30); pred,_,_=predict_ols(future,m)
        future['unrelated_future_label']=1e12
        again,_,_=predict_ols(future,m)
        np.testing.assert_array_equal(pred,again)
        np.testing.assert_allclose(predict_ols(train,m)[0],y,atol=1e-10)

    def test_iqr_zero_nonconstant_is_kept(self):
        d=self.fixture(); d['vol24']=0.;d.loc[99,'vol24']=1.
        m=fit_ols(d,np.arange(100),BASE)
        self.assertTrue(m['scaler']['vol24']['iqr_zero_nonconstant'])
        self.assertIn('vol24',m['active_columns'])

    def test_constant_is_dropped_and_unseen_coin_reference(self):
        d=self.fixture();d['vol24']=1.
        m=fit_ols(d,np.arange(100),BASE)
        self.assertIn('vol24',m['constant_columns'])
        p=d.iloc[:1].copy();p['symbol']='NEW'
        _,_,unseen=predict_ols(p,m);self.assertTrue(unseen[0])
        p0=p.copy();p0['symbol']=m['reference_coin']
        np.testing.assert_allclose(predict_ols(p,m)[0],predict_ols(p0,m)[0])

    def test_labels_entry_latency_exit_and_cost_once(self):
        ts=np.arange(100)*MINUTE
        d=pd.DataFrame({'ts':ts,'open':100+np.arange(100),'high':101+np.arange(100),'low':99+np.arange(100),'close':100+np.arange(100),'volume':1.,'quote_volume':100.})
        obs=pd.DataFrame({'observation_id':['a','b'],'symbol':['A','A'],'contract':['A','A'],'decision_ts':[0,0],'side':[1,-1]})
        lab=make_labels(obs,d)
        self.assertEqual(lab.entry_ts.iloc[0],MINUTE)
        expected=np.log(131/101)*10000
        self.assertAlmostEqual(lab.gross_bp_30.iloc[0],expected)
        self.assertAlmostEqual(lab.gross_bp_30.iloc[1],-expected)
        self.assertAlmostEqual(lab.net20bp_proxy_30.iloc[0],expected-20)
        # exit's future OHLCV is irrelevant: its open is all that was executed.
        d.loc[31,['high','low','close','volume','quote_volume']]=np.nan
        self.assertTrue(make_labels(obs,d).label_valid_30.all())
        d.loc[20,'volume']=0.
        self.assertFalse(make_labels(obs,d).label_valid_30.any())

    def test_future_missing_does_not_drop_opportunities(self):
        obs=pd.DataFrame({'observation_id':['a'],'symbol':['A'],'contract':['A'],'decision_ts':[0],'side':[1]})
        lab=make_labels(obs,pd.DataFrame())
        self.assertEqual(len(lab),1);self.assertFalse(lab.label_valid_30.iloc[0])

    def test_purge_and_boundary(self):
        d=pd.DataFrame({'decision_ts':[0,34*MINUTE,35*MINUTE,40*MINUTE]})
        self.assertEqual(temporal_mask(d,0,100*MINUTE).tolist(),[True,True,False,False])

    def test_bootstrap_holm_and_day_coin_equalweight(self):
        r=block_test(np.ones(91));self.assertEqual(r['p_raw'],1/2001)
        p=holm({'a':.001,'b':.02,'c':1.,'d':1.,'e':1.,'f':1.})
        self.assertAlmostEqual(p['a'],.006);self.assertAlmostEqual(p['b'],.10)
        d=pd.DataFrame({'decision_ts':[0,1,2],'symbol':['A','A','B']})
        q=daily_loss(d,np.array([2,2,4]),np.zeros(3),np.ones(3),0,DAY)
        self.assertAlmostEqual(q.difference.iloc[0],5.)

if __name__=='__main__':unittest.main()
