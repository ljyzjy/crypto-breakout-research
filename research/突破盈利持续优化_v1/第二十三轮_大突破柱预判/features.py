"""Point-in-time inputs for a first-minute large-candle prediction experiment."""
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
FEATURES=['prior_signed_body_atr','log_prior_pace','atr_fraction','trigger_age_seconds',
          'five_second_signed_move_atr','five_second_flow','log_five_second_relative_volume']
def build(year):
    data=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
    data=data[data.status.eq('verified')&data.source_year.eq(str(year))].copy()
    fp=(PARENT/'第二十二轮_五秒成交跨期探索'/'五秒主动成交特征_2024.parquet' if year==2024 else
        PARENT/'第十九轮_突破后五秒主动成交'/'五秒主动成交特征_2026.parquet')
    feat=pd.read_parquet(fp).rename(columns={'status':'flow_status','count':'flow_count','archive_sha256':'flow_sha'})
    d=data.merge(feat,on='observation_id',validate='one_to_one');assert len(d)==len(data)
    valid=(d.flow_status.eq('verified')&d.flow_count.ge(3)&(d.side*(d.raw_entry_5s-d.level)>0))
    d=d[valid].copy();d['tick_status']='verified'
    assert d.observation_id.is_unique and (d.window_end<=d.entry_exec_ts).all()
    assert (d.first_ts>d.decision_ts).all() and (d.last_ts<d.window_end).all()
    source=ROOT/'work'/('breakout_november_2026' if year==2026 else 'breakout_2024_11')/'normalized'
    pieces=[]
    for contract,g in d.groupby('contract'):
        raw=pd.read_parquet(source/f'{contract}_klines.parquet',columns=['ts','quote_volume']).set_index('ts')
        prev=raw.reindex(g.quarter_start.to_numpy('int64')-60_000).quote_volume.to_numpy(float)
        z=g.copy();z['previous_quote']=prev;pieces.append(z)
    d=pd.concat(pieces,ignore_index=True)
    d['prior_signed_body_atr']=d.side*d.prior_body_atr
    d['log_prior_pace']=np.log1p(d.prior_prefix_ratio)
    d['atr_fraction']=d.atr/d.level
    d['trigger_age_seconds']=(d.decision_ts-d.quarter_start)/1000
    d['five_second_signed_move_atr']=d.side*(d.raw_entry_5s-d.signal_close)/d.atr
    d['five_second_flow']=d.directional_imbalance
    d['log_five_second_relative_volume']=np.log1p(d.total_notional/d.previous_quote)
    valid=np.isfinite(d[FEATURES].to_numpy(float)).all(axis=1)&d.previous_quote.gt(0).to_numpy()
    d=d[valid].copy();d['model_feature_known_ts']=d.entry_exec_ts
    assert (d.model_feature_known_ts>=d.decision_ts+5000).all()
    return d.sort_values(['decision_ts','symbol']).reset_index(drop=True)
