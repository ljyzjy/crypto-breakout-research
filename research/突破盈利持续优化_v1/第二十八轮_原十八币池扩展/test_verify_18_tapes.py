"""Synthetic verification of first-direction ordering and strict 5-second flow."""
import json
from pathlib import Path
import pandas as pd
from verify_18_tapes import verified_row
HERE=Path(__file__).resolve().parent
e={'observation_id':'test','trigger_minute':0,'quarter_end':900_000,'upper':100.,'lower':90.,
   'long_known_eligible':True,'short_known_eligible':True,
   'long_spec':json.dumps({'stop_price':99.,'level':100.,'score':1.,'rank':1,'rvol':2.,'liquidity_rank':1}),
   'short_spec':json.dumps({'stop_price':91.,'level':90.,'score':-1.,'rank':1,'rvol':2.,'liquidity_rank':1})}
def tick(t,p,q,m,i):return {'transact_time':t,'price':p,'quantity':q,'is_buyer_maker':m,'agg_trade_id':i}
ticks=pd.DataFrame([tick(1000,100.1,3,'false',1),tick(2000,100.2,1,'false',2),
                    tick(3000,99.9,2,'true',3),tick(6000,100.15,4,'false',4),
                    tick(8000,100.3,1,'false',5),tick(59000,100.2,1,'true',6)])
r=verified_row(e,ticks,'x'*64)
assert r['status']=='verified' and r['side']==1 and r['decision_ts']==1000 and r['entry_exec_ts']==6000
assert r['five_count']==2 and r['window_end']==6000 and r['last_ts']==3000
assert abs(r['buy_notional']-100.2)<1e-10 and abs(r['sell_notional']-199.8)<1e-10
assert r['suffix_high']==100.3 and r['suffix_low']==100.15 and r['suffix_close']==100.2
both=pd.DataFrame([tick(1000,89.9,1,'true',1),tick(2000,100.2,1,'false',2),tick(6000,100.2,1,'false',3)])
assert verified_row({**e,'short_known_eligible':False},both,'x'*64)['status']=='first_direction_ineligible'
short=pd.DataFrame([tick(1000,89.9,1,'true',1),tick(2000,89.8,2,'true',2),
                    tick(3000,89.9,1,'false',3),tick(6000,89.8,1,'true',4),tick(59000,89.7,1,'true',5)])
y=verified_row(e,short,'x'*64)
assert y['status']=='verified' and y['side']==-1 and y['five_count']==2
assert y['five_imbalance']>0 and abs(y['five_imbalance']-(179.6-89.9)/(179.6+89.9))<1e-12
late=pd.DataFrame([tick(59000,100.1,1,'false',1),tick(60000,100.2,1,'false',2),
                   tick(64000,100.3,1,'false',3),tick(119000,100.4,1,'true',4)])
x=verified_row(e,late,'x'*64)
assert x['status']=='verified' and x['ts']==60_000 and x['entry_exec_ts']==64000 and x['suffix_close']==100.4
report={'first_actual_direction_priority':True,'five_second_strict_before_entry':True,
        'buyer_maker_long_short_direction':True,'cross_minute_entry_and_suffix':True}
(HERE/'十八币逐笔提取合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXPANDED18_SYNTHETIC_PASS',json.dumps(report),flush=True)
