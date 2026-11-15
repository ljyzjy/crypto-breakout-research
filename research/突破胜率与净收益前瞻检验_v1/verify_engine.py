"""Check target-only modification, original-engine parity and exit ordering."""
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
spec=importlib.util.spec_from_file_location('target_engine',HERE/'engine_target_copy.py')
eng=importlib.util.module_from_spec(spec);sys.modules[spec.name]=eng;spec.loader.exec_module(eng)
original=(P3/'engine.py').read_text(encoding='utf-8')
modified=(HERE/'engine_target_copy.py').read_text(encoding='utf-8')
old='stop=price-side*distance;target=price+side*2*distance'
new="stop=price-side*distance;target=price+side*float(scenario.get('target_r',2.))*distance"
assert original.count(old)==1 and original.replace(old,new)==modified

signals=pd.read_parquet(PREV/'signals.parquet');signals=signals[signals.sync_pass]
sc={'id':'parity','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':2.}
summary,curve,trades,entries,funding=eng.simulate(sc,signals,'2025-07-01','2026-04-26',
    market=Market(),guard=RankTrendGuard(),save=False,run_id='parity')
prior=json.loads((PREV/'early_sync_main_summary.json').read_text(encoding='utf-8'))
for key in ['trades','final_equity','return_pct','max_drawdown','fees','slippage_cost','funding_cost']:
    assert np.isclose(summary[key],prior[key],rtol=0,atol=1e-8),key
oldtrades=json.loads((PREV/'early_sync_main_trades.json').read_text(encoding='utf-8'))
assert [(t['observation_id'],t['entry_ts'],t['exit_ts'],t['reason']) for t in trades]==[(t['observation_id'],t['entry_ts'],t['exit_ts'],t['reason']) for t in oldtrades]

M=60_000; t0=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000); entry=t0+2*M
class FakeMarket:
    def __init__(self,collision=False):self.funding={};self.collision=collision
    def change_month(self,ts):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):
        if t==entry:return np.array([100.,101.1 if self.collision else 100.6,99.5 if self.collision else 99.8,100.2,100.,1e6])
        return np.array([100.2,100.3,99.8,100.2,100.,1e6])
class FakeGuard:
    def eligible(self,s,side,ts):return True
    def correlation(self,*args):return 0.
row={'ts':entry,'decision_ts':entry-M,'feature_known_ts':entry-M,'observation_id':'synthetic',
     'symbol':'BTCUSDT','contract':'BTCUSDT','side':1,'signal_close':100.,'atr':1.,
     'stop_price':99.6,'break_ts':t0,'touch_ts':t0,'score':1.,'rank':1,'rvol':2.,'liquidity_rank':1,'risk_multiplier':1.}
frame=pd.DataFrame([row])
def run(r,collision=False):
    s={'id':'synthetic','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':r}
    sm,cu,tr,en,fu=eng.simulate(s,frame,'2026-05-01','2026-05-01',market=FakeMarket(collision),guard=FakeGuard(),save=False)
    assert sm['valid_for_comparison'] and len(tr)==1
    return tr[0]
one=run(1.);two=run(2.);both=run(1.,True)
assert one['reason']=='target' and two['reason']=='time60' and both['reason']=='stop' and both['ambiguous']
report={'original_code_diff_only_target_multiple':True,'2r_full_historical_parity':True,
        'parity_trades':len(trades),'synthetic_1r_target':one['reason'],
        'synthetic_2r_unreached':two['reason'],'same_minute_stop_priority':both['reason']}
(HERE/'账户引擎验证.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('ENGINE_VALIDATED',json.dumps(report),flush=True)
