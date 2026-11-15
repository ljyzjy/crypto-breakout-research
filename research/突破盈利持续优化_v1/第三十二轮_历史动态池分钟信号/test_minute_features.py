"""Compare pre-rank BTC events to the existing generator and perturb the future."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from minute_features import derive,M
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;PARENT=HERE.parent
start=int(pd.Timestamp('2023-12-01',tz='UTC').timestamp()*1000);end=int(pd.Timestamp('2024-07-01',tz='UTC').timestamp()*1000)
grid=np.arange(start,end,M,dtype=np.int64);a=np.full((len(grid),7),np.nan)
source=pd.read_parquet(ROOT/'work'/'breakout_2024_expanded18'/'normalized'/'BTCUSDT_klines.parquet')
source=source[source.ts.between(start,end-1)].copy();assert not source.ts.duplicated().any()
ix=((source.ts.to_numpy(np.int64)-start)//M).astype(int)
a[ix]=source[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float)
pool=set(pd.date_range('2024-01-01','2024-06-29',freq='D',tz='UTC').strftime('%Y-%m-%d'))
_,rows,_=derive(a,grid,'BTCUSDT',2024,pool);ours=pd.DataFrame(rows).set_index('observation_id')
previous=PARENT/'第二十八轮_原十八币池扩展'
opening=pd.read_parquet(previous/'首分钟潜在候选_2024.parquet');opening=opening[opening.symbol.eq('BTCUSDT')].copy();opening['cohort']='opening'
later=pd.read_parquet(previous/'潜在触价候选_expanded_2024.parquet');later=later[later.symbol.eq('BTCUSDT')].copy();later['cohort']='touch'
old=pd.concat([opening,later],ignore_index=True);old=old[old.trigger_minute.lt(int(pd.Timestamp('2024-06-30',tz='UTC').timestamp()*1000))]
assert len(old)>5
for r in old.itertuples(index=False):
    assert r.observation_id in ours.index,(r.observation_id,'missing')
    z=ours.loc[r.observation_id]
    for attr in ('upper','lower','atr','prior_prefix_ratio','prior_body_atr'):
        assert np.isclose(float(z[attr]),float(getattr(r,attr)),rtol=1e-10,atol=1e-10),(r.observation_id,attr)
    for side,name in ((1,'long'),(-1,'short')):
        if getattr(r,name+'_known_eligible'):
            assert z[name+'_pre_rank']
            expected=json.loads(getattr(r,name+'_spec'));actual=json.loads(z[name+'_spec'])
            for key in ('stop_price','level'):assert np.isclose(expected[key],actual[key],rtol=1e-10,atol=1e-10)
chosen=old.sort_values('trigger_minute').iloc[0];index=int((int(chosen.trigger_minute)-start)//M)
future=a.copy();future[index+1:,1]+=5000.
_,again,_=derive(future,grid,'BTCUSDT',2024,pool);q=pd.DataFrame(again).set_index('observation_id')
assert chosen.observation_id in q.index
for key in ('upper','lower','atr','prior_prefix_ratio','prior_body_atr','long_pre_rank','short_pre_rank','long_spec','short_spec'):
    assert ours.loc[chosen.observation_id,key]==q.loc[chosen.observation_id,key],key
out={'old_btc_candidates_compared':len(old),'all_original_eligible_directions_preserved':True,
     'prior_features_and_stop_match':True,'later_minute_perturbation_no_effect':True,
     'candidate_is_only_possible_touch_not_tick_direction_or_fill':True}
(HERE/'分钟信号与原模型核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIVERSE32_MINUTE_FEATURE_TEST',json.dumps(out),flush=True)
