import unittest
import numpy as np
import pandas as pd
import risk_engine as r

class RiskChecks(unittest.TestCase):
 def test_known_risk_budget_and_clock(self):
  idx=pd.date_range('2022-01-01',periods=60*24,freq='h',tz='UTC')
  days=100*np.exp(np.cumsum(np.tile([.02,-.02],30)))
  c=np.repeat(days,24);d=pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':1.},index=idx)
  sigma=r.daily_vol(d);last=idx[-1]
  expected=np.std(np.tile([.02,-.02],10),ddof=1)
  self.assertAlmostEqual(sigma.loc[last],expected,places=12)
  self.assertEqual(set(sigma.dropna().index.hour),{23})
  data={(s,'1h'):d.copy() for s in r.SYMBOLS}
  b=r.sizing_frames(data,'vol_target200');self.assertAlmostEqual(b['BTCUSDT'].loc[last],2/expected,places=9)
  b=r.sizing_frames(data,'inverse_vol_pair');self.assertAlmostEqual(b['BTCUSDT'].loc[last],100,places=9)
  d.loc[idx[-25],'volume']=0
  self.assertTrue(pd.isna(r.daily_vol(d).loc[last]))

def validate():
 check=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RiskChecks));assert check.wasSuccessful()
 data,frames=r.inputs();notes=[]
 for resolution,delay in [('1h',0),('5m',0),('5m',5)]:
  base=r.engine.simulate('2025-01-01','2026-10-31','DailyMomentum',resolution=resolution,delay=delay,data=data,signal_frames=frames)
  control=r.simulate('2025-01-01','2026-10-31','fixed100',resolution=resolution,delay=delay,data=data,signal_frames=frames)
  assert base['orders']==control['orders'] and base['trades']==control['trades']
  assert base['final_equity']==control['final_equity'] and base['max_drawdown']==control['max_drawdown']
 notes.append('Fixed100 exactly reproduces original full later orders/trades/equity/drawdown in all three execution modes')
 for cut in ['2023-06-30 22:00','2024-06-30 23:00','2025-06-30 22:00']:
  t=pd.Timestamp(cut,tz='UTC');prefix={k:d.loc[:t].copy() for k,d in data.items() if k[1]=='1h'}
  changed={k:d.copy() for k,d in data.items() if k[1]=='1h'}
  for d in changed.values():d.loc[d.index>t,['open','high','low','close','volume']]*=13
  for policy in ['vol_cap100','vol_target200','inverse_vol_pair']:
   a=r.sizing_frames(data,policy);b=r.sizing_frames(prefix,policy);c=r.sizing_frames(changed,policy)
   for s in r.SYMBOLS:
    pd.testing.assert_series_equal(a[s].loc[:t],b[s],check_freq=False)
    pd.testing.assert_series_equal(a[s].loc[:t],c[s].loc[:t],check_freq=False)
 notes.append('All three risk policies invariant to truncation and future perturbation at three real cutoffs')
 for policy in ['vol_cap100','vol_target200','inverse_vol_pair']:
  for res,delay in [('1h',0),('5m',5)]:
   a=r.simulate('2025-01-01','2025-06-30',policy,resolution=res,delay=delay)
   b=r.simulate('2025-01-01','2025-07-03',policy,resolution=res,delay=delay)
   end=int(pd.Timestamp('2025-07-01',tz='UTC').timestamp())
   assert [x for x in a['orders'] if x['ts']<end and x['reason']!='window_end']==[x for x in b['orders'] if x['ts']<end and x['reason']!='window_end']
 notes.append('Three actual portfolio order prefixes unchanged by a later backtest end, hourly and5m delayed')
 return {'status':'PASS','synthetic_tests':check.testsRun,'real_checks':notes}
