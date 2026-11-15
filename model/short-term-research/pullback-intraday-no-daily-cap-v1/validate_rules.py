import unittest
from common import ROOT,SOURCE,load_contract,read,dump,sha
from features import frame,signals_for
import numpy as np,pandas as pd

class Rules(unittest.TestCase):
    def bars(self,side=1):
        # break -> pullback -> later recovery; no knowledge of subsequent bars.
        rows=[(60000,101,101.5,100.5,1,100,98),(120000,100.1,100.5,99.9,1,101.5,98),
              (180000,100.8,101,100,1,101.5,98)]
        d=pd.DataFrame(rows,columns=['ts','close','high','low','direction','prior_high','prior_low'])
        d['atr']=1.;d['valid']=True;d['quote_volume']=100000
        if side==-1:
            d[['close','high','low','prior_high','prior_low']]=pd.DataFrame({'close':200-d.close,'high':200-d.low,'low':200-d.high,'prior_high':200-d.prior_low,'prior_low':200-d.prior_high})
            d['direction']=-1
        return d
    def test_later_confirmation_and_structural_stop(self):
        for side in [1,-1]:
            r={(0,'X',side):{'score':side*2.,'rank':1,'rvol':2.}}
            out,_=signals_for(self.bars(side),r,'X','X');self.assertEqual(len(out),1)
            self.assertEqual(out.ts.iloc[0],180000);self.assertLess(out.touch_ts.iloc[0],out.ts.iloc[0])
            self.assertAlmostEqual(out.stop_price.iloc[0],99.8 if side==1 else 100.2)
    def test_invalidated_and_no_rank(self):
        d=self.bars();d.loc[1,'close']=99.
        r={(0,'X',1):{'score':2.,'rank':1,'rvol':2.}}
        self.assertTrue(signals_for(d,r,'X','X')[0].empty)
        self.assertTrue(signals_for(self.bars(),{},'X','X')[0].empty)
    def test_no_samebar_confirm(self):
        d=self.bars();d.loc[1,'close']=102
        self.assertTrue(signals_for(d.iloc[:2],{(0,'X',1):{'score':2.,'rank':1,'rvol':2.}},'X','X')[0].empty)
    def test_actual_data_prefix(self):
        cut=pd.Timestamp('2025-01-08T12:37Z');raw=load_contract('BTCUSDT','klines');raw=raw[raw.index<'2025-01-10']
        full,h,q=frame(raw);part,hp,qp=frame(raw[raw.index<cut])
        pd.testing.assert_frame_equal(h.loc[h.index<=cut],hp,check_freq=False)
        pd.testing.assert_frame_equal(q.loc[q.index<=cut],qp,check_freq=False)
        pd.testing.assert_frame_equal(full[full.ts<=int(cut.timestamp()*1000)],part,check_freq=False)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Rules))
    dump(ROOT/'rule-validation.json',{'passed':result.wasSuccessful(),'tests':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'actual_prefix':'BTCUSDT 2025-01-08T12:37Z'})
    raise SystemExit(0 if result.wasSuccessful() else 1)
