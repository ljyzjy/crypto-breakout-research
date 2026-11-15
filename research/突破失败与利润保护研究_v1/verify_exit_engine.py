"""Check no-rule parity and causal timing of modified exits with synthetic bars."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
GE=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge')
P3=GE/'outputs'/'feature-research-phase3'/'account'
PREV=HERE.parent/'突破柱融合研究_v1'
sys.path.insert(0,str(P3))
from account_market import Market,RankTrendGuard
spec=importlib.util.spec_from_file_location('exit_test_engine',HERE/'exit_engine.py')
eng=importlib.util.module_from_spec(spec);sys.modules[spec.name]=eng;spec.loader.exec_module(eng)

signals=pd.read_parquet(PREV/'signals.parquet');signals=signals[signals.sync_pass]
sc={'id':'parity','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':2.}
sm,curve,trades,entries,funding=eng.simulate(sc,signals,'2025-07-01','2026-04-26',
   market=Market(),guard=RankTrendGuard(),save=False,run_id='parity')
old=json.loads((PREV/'early_sync_main_summary.json').read_text(encoding='utf-8'))
old_trades=json.loads((PREV/'early_sync_main_trades.json').read_text(encoding='utf-8'))
for k in ['trades','final_equity','return_pct','max_drawdown','fees','slippage_cost','funding_cost']:
    assert np.isclose(sm[k],old[k],rtol=0,atol=1e-8),k
assert [(x['observation_id'],x['entry_ts'],x['exit_ts'],x['reason']) for x in trades]==[(x['observation_id'],x['entry_ts'],x['exit_ts'],x['reason']) for x in old_trades]

M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000);entry=base+2*M
default=np.array([100.6,101.,100.2,100.6,100.,1e6])
class FakeMarket:
    def __init__(self,bars):self.bars=bars;self.funding={}
    def change_month(self,ts):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):return np.array(self.bars.get(t,default),float)
class FakeGuard:
    def eligible(self,s,side,t):return True
    def correlation(self,*args):return 0.
row={'ts':entry,'decision_ts':base+M,'feature_known_ts':base+M,'observation_id':'synthetic',
     'symbol':'BTCUSDT','contract':'BTCUSDT','side':1,'signal_close':100.6,'atr':2.,
     'stop_price':99.,'level':100.5,'break_ts':base,'touch_ts':base,'score':1.,'rank':1,
     'rvol':2.,'liquidity_rank':1,'risk_multiplier':1.}
frame=pd.DataFrame([row])
def run(bars,**options):
    scenario={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':2.,**options}
    result,_,t,_,_=eng.simulate(scenario,frame,'2026-05-01','2026-05-01',
        market=FakeMarket(bars),guard=FakeGuard(),save=False,run_id='test')
    assert result['valid_for_comparison'] and len(t)==1
    return result,t[0]

lock_bars={base+4*M:[100.6,102.5,100.2,102.4,100.,1e6],
           base+9*M:[100.6,102.5,100.2,102.4,100.,1e6],
           base+10*M:[100.8,101.,100.5,100.8,100.,1e6]}
res,trade=run(lock_bars,lock_profit=True)
scheduled=[x for x in res['rule_events'] if x['kind']=='lock_scheduled']
applied=[x for x in res['rule_events'] if x['kind']=='lock_applied']
assert len(scheduled)==len(applied)==1
assert scheduled[0]['known_ts']==base+10*M and scheduled[0]['effective_ts']==base+11*M
assert applied[0]['effective_ts']==base+11*M and trade['exit_ts']==base+11*M and trade['reason']=='gap_stop'
assert trade['net']<0  # a stop modification never guarantees a positive result

failure_bars={base+14*M:[100.6,101.,100.2,100.4,100.,1e6],
              base+15*M:[100.3,100.5,100.2,100.3,100.,1e6]}
res2,trade2=run(failure_bars,failure_exit=True)
ev=[x for x in res2['rule_events'] if x['kind']=='failure_scheduled']
assert len(ev)==1 and ev[0]['known_ts']==base+15*M and ev[0]['effective_ts']==base+16*M
assert trade2['exit_ts']==base+16*M and trade2['reason']=='failed_breakout'
failure_bars[base+15*M]=[100.3,100.5,98.8,99.2,100.,1e6]
_,trade3=run(failure_bars,failure_exit=True)
assert trade3['reason']=='stop' and trade3['exit_ts']==base+16*M
report={'original_2r_parity':True,'parity_trades':len(trades),'complete_five_minute_required':True,
        'lock_one_minute_delay':True,'locked_stop_gap_may_lose':True,'failed_close_one_minute_delay':True,
        'prior_stop_precedes_scheduled_failure_exit':True}
(HERE/'退出规则合成与原策略核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXIT_ENGINE_VALIDATED',json.dumps(report),flush=True)
