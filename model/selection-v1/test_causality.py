"""Regression tests for information time, execution separation, and allocation."""
import unittest
import numpy as np
import pandas as pd
import engine

def fixture():
    idx=pd.date_range('2022-01-01','2024-04-01',tz='UTC');rng=np.random.default_rng(17);data={}
    for i,s in enumerate(['BTCUSDT','ETHUSDT','AUSDT','BUSDT','CUSDT','DUSDT','EUSDT','FUSDT']):
        c=100*np.exp(np.cumsum(rng.normal(.001,.025,len(idx))))
        data[s]=pd.DataFrame({'open':c,'high':c*1.025,'low':c*.975,'close':c,'volume':1e6,'quote_volume':2e7+i*1e6},index=idx)
    return data

class Causality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=fixture();cls.full=engine.simulate(cls.data,'2023-01-01','2024-04-01')

    def test_prefix_invariance(self):
        cut='2023-08-31'
        short=engine.simulate({s:d.loc[:cut] for s,d in self.data.items()},'2023-01-01',cut)
        self.assertEqual([t for t in self.full['trace'] if t['date']<=cut],short['trace'])
        self.assertEqual([o for o in self.full['orders'] if o['date']<=cut],
                         [o for o in short['orders'] if o['reason']!='window_end'])

    def test_future_prices_and_volume_cannot_change_past(self):
        data={s:d.copy() for s,d in self.data.items()}
        for d in data.values():d.loc['2023-09-01':,['open','high','low','close','quote_volume']]*=100
        changed=engine.simulate(data,'2023-01-01','2024-04-01')
        self.assertEqual([t for t in self.full['trace'] if t['date']<'2023-09-01'],
                         [t for t in changed['trace'] if t['date']<'2023-09-01'])

    def test_today_cannot_change_todays_decision(self):
        data={s:d.copy() for s,d in self.data.items()};cut='2023-08-28'
        for d in data.values():d.loc[cut,['open','high','low','close','quote_volume']]*=100
        changed=engine.simulate(data,'2023-01-01',cut)
        self.assertEqual(next(t for t in self.full['trace'] if t['date']==cut),changed['trace'][-1])

    def test_allocation_and_known_information(self):
        for t in self.full['trace']:
            self.assertLess(t['information_through'],t['date'])
            self.assertLessEqual(sum(t['weights'].values()),.20000001)
            self.assertTrue(all(0<=v<=.08000001 for v in t['weights'].values()))
            self.assertLessEqual(len(t['weights']),4)
            self.assertTrue(set(t['weights'])<=set(t['pool']))
        self.assertTrue(all(e['cash']>=-1e-8 for e in self.full['equity']))

    def test_fixed_universe_never_used_before_formation(self):
        with self.assertRaises(ValueError):engine.simulate(self.data,'2022-12-01','2023-02-01')

    def test_missing_held_data_is_not_hindsight_liquidation(self):
        buys=[o for o in self.full['orders'] if o['side']=='buy'];order=buys[0]
        data={s:d.copy() for s,d in self.data.items()}
        cut=pd.Timestamp(order['date'],tz='UTC')+pd.Timedelta(days=1)
        data[order['symbol']]=data[order['symbol']].loc[:cut-pd.Timedelta(days=1)]
        changed=engine.simulate(data,'2023-01-01','2024-04-01')
        # Never manufacture a fill on a day for which no bar exists.
        self.assertFalse(any(o['symbol']==order['symbol'] and o['date']>=str(cut.date()) for o in changed['orders']))

if __name__=='__main__':unittest.main(verbosity=2)
