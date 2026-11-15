import unittest
import numpy as np
import pandas as pd
import opt_engine as opt
from opt_engine import engine

def synthetic():
    idx=pd.date_range('2022-10-01',periods=70*24,freq='h',tz='UTC')
    close=np.arange(len(idx),dtype=float)/100+100
    d=pd.DataFrame({'open':close,'high':close+1,'low':close-1,'close':close,'volume':100.,'quote_volume':100*close,'trades':10.,'buy_quote':50*close},index=idx)
    data={(s,'1h'):d.copy() for s in engine.SYMBOLS}
    f={s:engine.features(d) for s in engine.SYMBOLS}
    return data,f

class VariantChecks(unittest.TestCase):
    def test_daily_availability_and_missing_day(self):
        d,_=synthetic();x=d[('BTCUSDT','1h')]
        m=opt.completed_daily_momentum(x,x.index)
        self.assertTrue(pd.isna(m.loc['2022-10-31 22:00']))
        self.assertGreater(m.loc['2022-10-31 23:00'],0)
        day=pd.Timestamp('2022-11-05',tz='UTC');modified=x.copy()
        modified.loc[day+pd.Timedelta(hours=15):,'close']*=10
        alt=opt.completed_daily_momentum(modified,modified.index)
        pd.testing.assert_series_equal(m.loc[:day+pd.Timedelta(hours=22)],alt.loc[:day+pd.Timedelta(hours=22)])
        missing=x.drop(day+pd.Timedelta(hours=12))
        mm=opt.completed_daily_momentum(missing.reindex(x.index),x.index)
        self.assertEqual(mm.loc[day+pd.Timedelta(hours=23)],m.loc[day-pd.Timedelta(hours=1)])

    def test_four_hour_source_clock(self):
        d,f=synthetic()
        for s in engine.SYMBOLS:f[s]['breakout_buy']=True
        a=opt.signal_frames(d,f,'breakout_4h_entry')
        for s in engine.SYMBOLS:
            self.assertEqual(set(a[s].index[a[s].breakout_buy].hour),{3,7,11,15,19,23})

    def test_cost_threshold_and_strict_boundary(self):
        d,f=synthetic();fee=.001;slip=.0005
        threshold=opt.cost_threshold(fee,slip)
        pnl=-100*(1+fee)+100/(1+slip)*(1+threshold)*(1-slip)*(1-fee)
        self.assertAlmostEqual(pnl,0,places=10)
        self.assertGreater(opt.cost_threshold(.002),threshold)
        for s in engine.SYMBOLS:
            f[s]['reversion_buy']=True
            x=d[(s,'1h')];x['close']=1.
            f[s]['vwap24']=1+threshold
        a=opt.signal_frames(d,f,'reversion_cost_room',fee)
        for s in engine.SYMBOLS:
            self.assertFalse(a[s].reversion_buy.any())
            f[s]['vwap24']=1+threshold+1e-8
        a=opt.signal_frames(d,f,'reversion_cost_room',fee)
        self.assertTrue(a['BTCUSDT'].reversion_buy.all())

    def test_only_registered_entry_column_changes(self):
        d,f=synthetic();saved={s:v.copy(deep=True) for s,v in f.items()}
        for variant,definition in opt.VARIANTS.items():
            a=opt.signal_frames(d,f,variant)
            for s in engine.SYMBOLS:
                pd.testing.assert_frame_equal(f[s],saved[s])
                col=definition['parent']+'_buy'
                pd.testing.assert_frame_equal(f[s].drop(columns=col),a[s].drop(columns=col))
                self.assertTrue((~a[s][col] | f[s][col]).all())

def real_checks():
    data,original=engine.inputs();notes=[]
    # Existing engine and data must reproduce the original actual ledgers.
    for parent in ['DailyMomentum','breakout','reversion']:
        actual=engine.simulate('2025-01-01','2026-10-31',parent,data=data,signal_frames=original)
        expected=engine.read(engine.ROOT/'results'/f'2025-01-01_2026-10-31_{parent}_10_1h_d0.json.gz')
        assert actual['trades']==expected['trades'] and actual['orders']==expected['orders']
        assert abs(actual['final_equity']-expected['final_equity'])<1e-8
    notes.append('Three original full later ledgers reproduced exactly')
    for cut in ['2023-06-30 23:00','2024-06-30 23:00','2025-06-30 23:00']:
        t=pd.Timestamp(cut,tz='UTC')
        prefix={k:v.loc[:t].copy() for k,v in data.items() if k[1]=='1h'}
        pf={s:engine.features(prefix[(s,'1h')]) for s in engine.SYMBOLS}
        changed={k:v.copy() for k,v in data.items() if k[1]=='1h'}
        for x in changed.values():
            x.loc[x.index>t,['open','high','low','close','volume','quote_volume','buy_quote']]*=13
        cf={s:engine.features(changed[(s,'1h')]) for s in engine.SYMBOLS}
        for variant in opt.VARIANTS:
            for fee in [.001,.002,.003]:
                full=opt.signal_frames(data,original,variant,fee)
                truncated=opt.signal_frames(prefix,pf,variant,fee)
                disturbed=opt.signal_frames(changed,cf,variant,fee)
                for s in engine.SYMBOLS:
                    pd.testing.assert_frame_equal(full[s].loc[:t],truncated[s],check_freq=False)
                    pd.testing.assert_frame_equal(full[s].loc[:t],disturbed[s].loc[:t],check_freq=False)
        notes.append('All variant/fee signal prefixes and future perturbations passed at '+cut)
    for variant in opt.VARIANTS:
        for resolution,delay,start,end,extended in [('1h',0,'2025-01-01','2025-06-30','2025-07-03'),('5m',5,'2025-01-01','2025-01-31','2025-02-03')]:
            short=opt.simulate(start,end,variant,resolution=resolution,delay=delay,data=data,original=original)
            long=opt.simulate(start,extended,variant,resolution=resolution,delay=delay,data=data,original=original)
            cutoff=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp())
            a=[o for o in short['orders'] if o['ts']<cutoff and o['reason']!='window_end']
            b=[o for o in long['orders'] if o['ts']<cutoff and o['reason']!='window_end']
            assert a==b,(variant,resolution)
    notes.append('Three actual order prefixes invariant for hourly and five-minute delayed execution')
    return notes

def run():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(VariantChecks)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise RuntimeError('Optimization unit validation failed')
    return {'status':'PASS','unit_tests':result.testsRun,'real_checks':real_checks()}

if __name__=='__main__':print(run())
