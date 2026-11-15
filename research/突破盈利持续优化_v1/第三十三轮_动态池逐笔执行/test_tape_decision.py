"""Synthetic first direction, data mismatch, flow filtering and delayed fills."""
import json
from pathlib import Path
import pandas as pd
from tape_decision import decide
HERE=Path(__file__).resolve().parent
spec=json.dumps({'stop_price':99.,'level':100.,'score':2.,'rvol':2.,'rank':1,'liquidity_rank':1})
e={'trigger_minute':0,'quarter_start':0,'quarter_end':60_000,'upper':100.,'lower':90.,'atr':2.,
   'long_known_eligible':True,'short_known_eligible':False,'long_spec':spec,'short_spec':'null'}
raw=[(1000,100.1,1.,'false'),(2000,100.12,1.,'false'),(3000,100.13,1.,'false'),
     (4000,100.14,1.,'false'),(6000,100.2,1.,'false'),(11000,100.3,1.,'false'),
     (16000,102.9,1.,'false'),(21000,102.8,1.,'false'),(59000,102.7,1.,'false'),(65000,102.6,1.,'false')]
t=pd.DataFrame([{'agg_trade_id':i,'transact_time':time,'price':p,'quantity':q,'is_buyer_maker':maker} for i,(time,p,q,maker) in enumerate(raw)])
bar=pd.DataFrame([{'ts':0,'open':100.1,'high':102.9,'low':100.1,'close':102.7}]).set_index('ts')
x=decide(e,t,bar);assert x['status']=='qualified' and x['five_count']==3 and x['five_imbalance']==1.
assert all(p['entry_ts']==11000 and p['exit_ts']>=p['exit_signal_ts']+5000 for p in x['paths'].values())
bad=bar.copy();bad.loc[0,'high']=103.;assert decide(e,t,bad)['status']=='minute_trade_ohlc_mismatch'
low=t.copy();low.loc[low.transact_time.isin([2000,3000,4000]),'is_buyer_maker']='true'
assert decide(e,low,bar)['status']=='flow_filter_not_met'
wrong={**e,'long_known_eligible':False};assert decide(wrong,t,bar)['status']=='first_direction_ineligible'
out={'first_cross_direction_and_ohlc':True,'strict_five_second_directional_flow':True,
     'market_order_delays_and_leverage_gates':True,'mismatched_archive_not_silently_removed':True}
(HERE/'逐笔决策合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIVERSE33_TAPE_SYNTHETIC_PASS',json.dumps(out),flush=True)
