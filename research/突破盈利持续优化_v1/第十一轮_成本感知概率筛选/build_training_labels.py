"""Create causal pre-entry features and completed standalone training outcomes."""
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
R2=PARENT/'第二轮_成本空间与即时成交';R6=PARENT/'第六轮_柱内首次触价'
R8=PARENT/'第八轮_BTC短时领先';R9=PARENT/'第九轮_突破后延长持仓'
for p in (PARENT,R2,R6,R8,R9):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_extended as extended

FEATURES=['body_dir_atr','log_pace','atr_fraction','quarter_phase','trigger_overshoot_atr',
          'arrival_move_atr','observed_stop_fraction','btc_prev_dir','eth_prev_dir','asset_prev_dir',
          'log_hourly_rvol','direction']
def build_features(d):
    x=d.copy();side=x.side.astype(float)
    x['body_dir_atr']=side*x.prior_body_atr
    x['log_pace']=np.log(x.prior_prefix_ratio.where(x.prior_prefix_ratio>0))
    x['atr_fraction']=x.atr/x.level
    x['quarter_phase']=(x.trigger_minute-x.quarter_start)/60_000
    x['trigger_overshoot_atr']=side*(x.signal_close-x.level)/x.atr
    x['arrival_move_atr']=side*(x.raw_entry_5s-x.signal_close)/x.atr
    fill=x.raw_entry_5s*(1+side*.0005)
    x['observed_stop_fraction']=side*(fill-x.stop_price)/fill
    x['btc_prev_dir']=side*x.btc_prev_return;x['eth_prev_dir']=side*x.eth_prev_return
    x['asset_prev_dir']=side*x.asset_prev_return
    x['log_hourly_rvol']=np.log(x.rvol.where(x.rvol>0));x['direction']=side
    return x
def main():
    rows=[];excluded=[];feature_total=0
    for year,tag,cutoff in [(2023,'later','2023-12-31'),(2024,None,'2024-06-30')]:
        name=f'{year}触价前市场特征'+(f'_{tag}' if tag else '')+'.parquet'
        data=pd.read_parquet(R8/name)
        cutoff_ms=int(pd.Timestamp(cutoff,tz='UTC').timestamp()*1000)
        data=data[data.status.eq('verified')&data.decision_ts.lt(cutoff_ms)].copy()
        data=build_features(data);feature_total+=len(data)
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        sc={'id':'unit_label','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':1.,
            'leverage':20,'stop_shock':0.,'max_hold_minutes':240,'allow_overnight':True}
        for n,(_,record) in enumerate(data.iterrows(),1):
            if not np.isfinite(record[FEATURES].to_numpy(float)).all():
                excluded.append({'id':record.observation_id,'reason':'feature_missing'});continue
            ts=pd.Timestamp(int(record.ts),unit='ms',tz='UTC')
            start=ts.strftime('%Y-%m-%d');end=(ts+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            one=pd.DataFrame([record.to_dict()]).drop(columns=['large_1pct_label','large_halfpct_label','completed_body_pct'])
            sm,_,trades,entries,funding=extended.engine.simulate(sc,one,start,end,market=market,guard=guard,save=False,run_id='unit_label')
            if not sm['valid_for_comparison']:raise RuntimeError(f"unit_invalid:{record.observation_id}:{sm['issues']}")
            if not trades:
                excluded.append({'id':record.observation_id,'reason':'entry_rejected','details':sm['rejection_counts']});continue
            assert len(trades)==1 and len(entries)==1
            trade=trades[0]
            train_cutoff=int(pd.Timestamp('2024-07-01',tz='UTC').timestamp()*1000)
            if trade['exit_ts']>=train_cutoff:raise RuntimeError('training_outcome_after_cutoff')
            if trade['reason']=='period_end':raise RuntimeError('forced_label_at_data_boundary')
            assert abs(sum(x['actual_charge'] for x in funding)-trade['funding'])<1e-8
            row={'observation_id':record.observation_id,'source_year':year,'entry_ts':trade['entry_ts'],
                 'exit_ts':trade['exit_ts'],'target':int(trade['net']>0),
                 'net_pct_notional':100*trade['net']/trade['entry_notional'],
                 'net_usdt_unit_account':trade['net'],'entry_notional':trade['entry_notional'],
                 'funding_usdt':trade['funding'],'reason':trade['reason']}
            row.update({col:float(record[col]) for col in FEATURES});rows.append(row)
            if n%50==0:print('LABELS',year,n,'/',len(data),'accepted',len(rows),flush=True)
        del market,guard,data;gc.collect()
    frame=pd.DataFrame(rows).sort_values('entry_ts').reset_index(drop=True)
    assert frame.observation_id.is_unique and np.isfinite(frame[FEATURES].to_numpy()).all()
    frame.to_parquet(HERE/'训练期已完成单笔标签.parquet',index=False)
    meta={'feature_candidates':feature_total,'accepted_unit_outcomes':len(frame),'excluded_count':len(excluded),
          'exclusions':excluded,'net_wins':int(frame.target.sum()),'features':FEATURES,
          'label_note':'One-at-a-time counterfactual account; actual portfolio evaluation is separate.'}
    flow.dump(HERE/'训练标签核对.json',meta)
    print('TRAIN_LABELS_READY',len(frame),'wins',meta['net_wins'],'excluded',len(excluded),flush=True)
if __name__=='__main__':main()
