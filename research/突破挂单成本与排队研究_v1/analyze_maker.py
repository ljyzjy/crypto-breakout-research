"""Paired outcome and post-hoc source-quality sensitivity diagnostics."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_maker_tapes_2026'
out=pd.read_parquet(HERE/'逐信号订单模拟.parquet')
plans=pd.read_parquet(HERE/'逐信号计划与状态.parquet')
q=pd.read_csv(HERE/'逐笔对分钟成交额核验.csv').set_index('observation_id')
old=pd.read_csv(WORK/'first_run_summary.csv').set_index('variant')
now=pd.read_csv(HERE/'挂单与吃单机会对照.csv').set_index('variant')
for col in ['common_plans','orders_filled_any','filled_net_win_pct','mean_net_u_per_common_opportunity','mean_net_bp_per_planned_notional']:
    assert np.allclose(old[col],now[col],equal_nan=True),col

zeros={'unfilled_expired','not_submitted_entry_deviation','not_submitted_stop_cost','not_submitted_after_quarter'}
data=out.copy();data['outcome_known']=data.status.eq('filled')|data.status.isin(zeros)
data['net_known']=np.where(data.status.eq('filled'),data.net,np.where(data.status.isin(zeros),0.,np.nan))
data['net_bp']=data.net_known/data.planned_notional*10000
data['clean_window']=data.observation_id.map(q.bad_minutes_gt_1pct).eq(0)
data['clean_entry']=data.observation_id.map(q.entry_bad_minutes_gt_1pct).eq(0)
rows=[]
for scope,mask in [('all',data.outcome_known),('entire_window_consistent',data.outcome_known&data.clean_window),
                   ('entry_window_consistent',data.outcome_known&data.clean_entry)]:
    for variant,g in data[mask].groupby('variant'):
        f=g[g.status.eq('filled')]
        rows.append({'scope':scope,'variant':variant,'n':len(g),'filled':len(f),
                     'net_win_pct_among_filled':float(100*f.net.gt(0).mean()) if len(f) else None,
                     'mean_net_bp_per_planned_opportunity':float(g.net_bp.mean()) if len(g) else None,
                     'mean_net_u_per_opportunity':float(g.net_known.mean()) if len(g) else None})
pd.DataFrame(rows).to_csv(HERE/'数据一致性敏感性.csv',index=False,encoding='utf-8-sig')

period=pd.date_range('2026-05-01','2026-10-31',freq='D').strftime('%Y-%m-%d')
n=len(period);rng=np.random.default_rng(20261114);starts=rng.integers(0,n-6,size=(3000,int(np.ceil(n/7))))
idx=(starts[:,:,None]+np.arange(7)).reshape(3000,-1)[:,:n]
comparisons=[]
for target in ['2r','1r']:
    base=data[(data.variant==f'market_{target}')&data.outcome_known].set_index('observation_id')
    for queue in [0,10,100]:
        lim=data[(data.variant==f'limit_q{queue}_{target}')&data.outcome_known].set_index('observation_id')
        pair=base[['net_bp','signal_ts','status','net_known']].join(lim[['net_bp','status','net_known']],how='inner',lsuffix='_mkt',rsuffix='_lim')
        pair['difference_bp']=pair.net_bp_lim-pair.net_bp_mkt
        pair['day']=pd.to_datetime(pair.signal_ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
        daily=pair.groupby('day').difference_bp.agg(['sum','count']).reindex(period,fill_value=0)
        count=daily['count'].to_numpy()[idx].sum(axis=1);total=daily['sum'].to_numpy()[idx].sum(axis=1)
        boot=np.divide(total,count,out=np.full(len(total),np.nan),where=count>0)
        ci=np.nanquantile(boot,[.025,.975])
        missed=pair[(pair.status_lim=='unfilled_expired')&(pair.net_known_mkt>0)]
        comparisons.append({'target':target,'queue_multiple':queue,'paired_opportunities':len(pair),
          'maker_minus_market_bp_mean':float(pair.difference_bp.mean()),
          'block95_low_bp':float(ci[0]),'block95_high_bp':float(ci[1]),
          'maker_unfilled_market_would_profit':len(missed),
          'maker_unfilled_market_positive_u':float(missed.net_known_mkt.sum())})
pd.DataFrame(comparisons).to_csv(HERE/'配对改善与机会成本.csv',index=False,encoding='utf-8-sig')
report={'replay_instrumentation_did_not_change_results':True,'common_plans_ready':int(plans.status.eq('ready').sum()),
        'data_quality_conditioning_note':'Excluding a later-window mismatch uses future data; sensitivity only, not a live filter.',
        'bootstrap_note':'7-day moving-block bootstrap on matched normalized differences; exploratory, small sample, no multiple-testing adjustment.',
        'paired':comparisons}
(HERE/'配对与敏感性说明.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
