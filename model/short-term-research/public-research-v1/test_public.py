import unittest
import numpy as np
import pandas as pd
import public_engine as p

class SignalChecks(unittest.TestCase):
 def test_availability_and_no_future(self):
  index=pd.date_range('2022-01-01',periods=5000,freq='h',tz='UTC')
  c=100+np.arange(len(index))*.01
  d=pd.DataFrame({'open':c,'high':c+1,'low':c-1,'close':c,'volume':100.},index=index)
  for variant,spec in p.VARIANTS.items():
   f=p.signals(d,variant);t=index[4750]
   altered=d.copy();altered.loc[altered.index>t,'close']*=.1
   pd.testing.assert_frame_equal(f.loc[:t],p.signals(altered,variant).loc[:t])
   pd.testing.assert_frame_equal(f.loc[:t],p.signals(d.loc[:t],variant))
   self.assertTrue(f.DailyMomentum_buy.any())
   hours=f.index[f.DailyMomentum_buy]
   self.assertTrue(all((hours.hour+1)%spec['hours']==0))
   self.assertFalse(f.DailyMomentum_sell.any())
   if variant=='ewmac_ensemble':self.assertFalse(f.DailyMomentum_buy.iloc[:4095].any())

def validate():
 r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SignalChecks))
 assert r.wasSuccessful()
 data,_=p.engine.inputs();notes=[]
 for cut in ['2023-06-30 22:00','2024-06-30 22:00','2025-06-30 22:00']:
  t=pd.Timestamp(cut,tz='UTC');prefix={k:v.loc[:t].copy() for k,v in data.items() if k[1]=='1h'}
  disturbed={k:v.copy() for k,v in data.items() if k[1]=='1h'}
  for d in disturbed.values():d.loc[d.index>t,['open','high','low','close','volume']]*=13
  for variant in p.VARIANTS:
   f=p.cached_signals(variant);a=p.signal_frames(prefix,variant);b=p.signal_frames(disturbed,variant)
   for s in p.engine.SYMBOLS:
    pd.testing.assert_frame_equal(f[s].loc[:t],a[s],check_freq=False)
    pd.testing.assert_frame_equal(f[s].loc[:t],b[s].loc[:t],check_freq=False)
  notes.append('All variants future-perturbation and truncated-prefix invariant at '+cut)
 for variant in p.VARIANTS:
  for resolution,delay in [('1h',0),('5m',5)]:
   a=p.simulate('2025-01-01','2025-06-30',variant,resolution=resolution,delay=delay)
   b=p.simulate('2025-01-01','2025-07-03',variant,resolution=resolution,delay=delay)
   end=int(pd.Timestamp('2025-07-01',tz='UTC').timestamp())
   assert [x for x in a['orders'] if x['ts']<end and x['reason']!='window_end']==[x for x in b['orders'] if x['ts']<end and x['reason']!='window_end']
 notes.append('All three actual order prefixes invariant under longer backtest, hourly and five-minute delayed')
 return {'status':'PASS','synthetic_tests':r.testsRun,'real_checks':notes}
