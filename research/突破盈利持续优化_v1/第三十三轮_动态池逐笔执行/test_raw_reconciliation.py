"""Check raw source reconciliation never hides a changed breakout or trade path."""
import json
from pathlib import Path
import pandas as pd
from raw_reconciliation import reconcile
HERE=Path(__file__).resolve().parent
spec=json.dumps({'stop_price':99.,'level':100.,'score':2.,'rvol':2.,'rank':1,'liquidity_rank':1})
e={'trigger_minute':0,'quarter_start':0,'quarter_end':60_000,'upper':100.,'lower':90.,'atr':2.,
   'long_known_eligible':True,'short_known_eligible':False,'long_spec':spec,'short_spec':'null'}
rows=[(1000,100.1),(2000,100.),(3000,100.13),(4000,100.14),(6000,100.2),(11000,100.3),
      (16000,102.9),(21000,102.8),(59000,102.7),(65000,102.6)]
def make(z):return pd.DataFrame([{'agg_trade_id':i,'transact_time':t,'price':p,'quantity':1.,'is_buyer_maker':'false'} for i,(t,p) in enumerate(z)]).sort_values(['transact_time','agg_trade_id']).reset_index(drop=True)
agg=make(rows);raw=make([(500,100.),*rows]);bars=pd.DataFrame([{'ts':0,'open':100.,'high':102.9,'low':100.,'close':102.7}]).set_index('ts')
x=reconcile(e,agg,raw,bars);assert x['reconciled'] and len(x['paths_checked'])==4
changed=make([(500,100.),(750,100.11),*rows])
assert reconcile(e,agg,changed,bars)['reason']=='first_cross_mismatch'
changed2=raw.copy();changed2.loc[changed2.transact_time.eq(3000),'quantity']=2.
assert reconcile(e,agg,changed2,bars)['reason']=='five_second_flow_mismatch'
out={'open_only_mismatch_reconciled_with_exact_raw_path':True,'different_first_cross_rejected':True,
     'different_directional_flow_rejected':True,'both_leverages_and_exits_replayed':True}
(HERE/'原始成交复核合成测试.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIVERSE33_RAW_RECONCILIATION_TEST',json.dumps(out),flush=True)
