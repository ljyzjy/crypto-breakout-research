"""Accounting, chronology and real-data causal checks for the isolated research engine."""
import importlib.util
import json
import unittest
import numpy as np
import pandas as pd
from st_engine import ROOT,KIT,SYMBOLS,MODES,features,simulate,inputs,dump


def fixture():
    index=pd.date_range('2022-12-30', '2023-01-02',freq='h',tz='UTC')
    d=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':100.,'quote_volume':10000.,'trades':10.,'buy_quote':5000.},index=index)
    data={(s,'1h'):d.copy() for s in SYMBOLS}
    f={s:features(d) for s in SYMBOLS}
    for frame in f.values():
        for mode in MODES:frame[mode+'_buy']=False;frame[mode+'_sell']=False
    return data,f


class EngineChecks(unittest.TestCase):
    def test_next_bar_and_current_bar(self):
        d,f=fixture();stamp=pd.Timestamp('2023-01-01',tz='UTC');f['BTCUSDT'].loc[stamp,'breakout_buy']=True
        a=simulate('2023-01-01','2023-01-01','breakout',data=d,signal_frames=f)
        self.assertEqual(a['orders'][0]['ts'],int((stamp+pd.Timedelta(hours=1)).timestamp()))
        self.assertEqual(a['orders'][0]['information_ts'],a['orders'][0]['ts'])
        d[('BTCUSDT','1h')].loc[stamp+pd.Timedelta(hours=1),['high','close','quote_volume','buy_quote']]=[999.,200.,1e8,9e7]
        b=simulate('2023-01-01','2023-01-01','breakout',data=d,signal_frames=f)
        self.assertEqual(a['orders'][0],b['orders'][0])

    def test_round_trip_cost_and_cash(self):
        d,f=fixture();f['BTCUSDT'].loc['2022-12-31 23:00','breakout_buy']=True
        a=simulate('2023-01-01','2023-01-01','breakout',data=d,signal_frames=f)
        expected=1000-100*1.001+(100/(100*1.0005))*100*.9995*.999
        self.assertAlmostEqual(a['final_equity'],expected,places=9)
        self.assertAlmostEqual(sum(t['pnl'] for t in a['trades']),a['final_equity']-1000,places=9)
        self.assertAlmostEqual(a['gross_pnl'],0,places=9)
        self.assertEqual(a['open_positions'],0)

    def test_gap_stop(self):
        d,f=fixture();f['BTCUSDT'].loc['2022-12-31 23:00','breakout_buy']=True
        d[('BTCUSDT','1h')].loc['2023-01-01 01:00',['open','low','close']]=[90,89,90]
        a=simulate('2023-01-01','2023-01-01','breakout',data=d,signal_frames=f)
        self.assertEqual(a['trades'][0]['reason'],'gap_stop')
        self.assertAlmostEqual(a['trades'][0]['exit_price'],90*.9995)

    def test_global_stop_and_no_same_bar_foresight(self):
        d,f=fixture()
        for s in SYMBOLS:
            f[s]['breakout_buy']=True
            d[(s,'1h')].loc['2023-01-01 00:00','low']=90
        a=simulate('2023-01-01','2023-01-01','breakout',data=d,signal_frames=f)
        buys=[o for o in a['orders'] if o['side']=='buy']
        self.assertEqual(len(buys),2)  # Both opens precede either intrabar low.
        self.assertEqual(buys[0]['ts'],buys[1]['ts'])
        self.assertEqual(a['guard_activations'],1)
        self.assertEqual(a['trade_count'],2)

    def test_cooldown_and_time_exit(self):
        d,f=fixture();f['BTCUSDT']['reversion_buy']=True
        a=simulate('2023-01-01','2023-01-01','reversion',data=d,signal_frames=f)
        regular=[t for t in a['trades'] if t['reason']!='window_end']
        self.assertTrue(all(t['hold_hours']==6 for t in regular))
        for prev,nxt in zip(a['trades'],a['trades'][1:]):self.assertGreaterEqual(nxt['entry_ts']-prev['exit_ts'],6*3600)

    def test_missing_clock_and_zero_volume(self):
        idx=pd.date_range('2022-10-01',periods=1000,freq='h',tz='UTC')
        d=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':100.,'quote_volume':10000.,'trades':10.,'buy_quote':5000.},index=idx)
        d=d.drop(idx[900]);f=features(d)
        self.assertTrue(pd.isna(f.loc[idx[920],'M24']))
        self.assertFalse(f.loc[idx[920],'pullback_buy'])
        d.loc[idx[950],['volume','quote_volume','buy_quote']]=0
        f=features(d);self.assertTrue(pd.isna(f.loc[idx[950],'TBI4']))


def real_checks():
    data,fs=inputs();notes=[]
    # The research comparator must use the deployed strategy's actual daily signals.
    spec=importlib.util.spec_from_file_location('daily_original',KIT/'user_data/strategies/DailyCandidates.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    strategy=module.DailyMomentum({})
    for s in SYMBOLS:
        raw=data[(s,'1h')].reset_index().rename(columns={'index':'date'})
        orig=strategy.populate_indicators(raw.copy(),{})
        orig=strategy.populate_entry_trend(orig,{})
        orig=strategy.populate_exit_trend(orig,{})
        expected=fs[s].reindex(raw.date)
        assert np.array_equal(orig.enter_long.astype(bool).to_numpy(),expected.DailyMomentum_buy.to_numpy())
        assert np.array_equal(orig.exit_long.astype(bool).to_numpy(),expected.DailyMomentum_sell.to_numpy())
    notes.append('DailyMomentum entry/exit signals match deployed DailyCandidates.py for both entire hourly histories')
    for cutoff in ('2023-06-30 23:00','2024-06-30 23:00','2025-06-30 23:00'):
        ts=pd.Timestamp(cutoff,tz='UTC')
        for s in SYMBOLS:
            prefix=features(data[(s,'1h')].loc[:ts])
            pd.testing.assert_frame_equal(prefix,fs[s].loc[:ts],check_freq=False)
            changed=data[(s,'1h')].copy();mask=changed.index>ts
            changed.loc[mask,['open','high','low','close','volume','quote_volume','buy_quote']]*=13
            pd.testing.assert_frame_equal(features(changed).loc[:ts],fs[s].loc[:ts],check_freq=False)
        notes.append('Feature/signal prefix and future-price/volume perturbation passed at '+cutoff)
    # Actual order prefixes: an administrative closing trade at a chosen cut is excluded.
    for mode in MODES:
        long=simulate('2025-01-01','2025-07-05',mode,data=data,signal_frames=fs)
        short=simulate('2025-01-01','2025-06-30',mode,data=data,signal_frames=fs)
        cut=int(pd.Timestamp('2025-07-01',tz='UTC').timestamp())
        a=[o for o in long['orders'] if o['ts']<cut and o['reason']!='window_end']
        b=[o for o in short['orders'] if o['ts']<cut and o['reason']!='window_end']
        assert a==b,mode
    notes.append('All six actual order prefixes invariant at 2025-06-30; administrative closes excluded')
    burn=[]
    for s in SYMBOLS:
        alt=features(data[(s,'1h')].loc['2022-12-01':]);ref=fs[s].loc['2023-01-01':]
        alt=alt.loc[ref.index]
        error=float(((alt.ema72-ref.ema72).abs()/ref.ema72).max())
        differences=int((alt.pullback_buy!=ref.pullback_buy).sum())
        assert error<1e-7 and differences==0,(s,error,differences)
        burn.append({'symbol':s,'max_relative_ema72_error':error,'entry_signal_differences':differences})
    return {'status':'PASS','checks':notes,'ema_burn_in':burn}


if __name__=='__main__':
    import sys
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(EngineChecks)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    report={'synthetic_tests':result.testsRun,'synthetic_status':'PASS'}
    if '--real' in sys.argv:report.update(real_checks())
    dump(ROOT/'validation.json',report);print(json.dumps(report,ensure_ascii=False))
