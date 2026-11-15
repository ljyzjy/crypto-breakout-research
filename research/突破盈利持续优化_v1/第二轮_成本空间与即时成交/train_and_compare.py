"""Predeclared second-round training and internally reused historical checks."""
import gc
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROOT=HERE.parent.parent.parent
sys.path.insert(0,str(PARENT))
import flow_research as flow

flow.HERE=HERE;flow.research.HERE=HERE
M=60_000
NAMES=['base_1r','room_1r','aligned_1r','aligned_room_1r','opposing_1r','opposing_room_1r','early_room_1r']
def select(signals,name):
    result=signals
    if name.startswith('aligned_'):result=result[result.signal_minute_imbalance.ge(0)]
    if name.startswith('opposing_'):result=result[result.signal_minute_imbalance.lt(0)]
    if 'room_' in name:result=result[result.signal_stop_fraction.ge(.0045)]
    if name.startswith('early_'):result=result[(result.ts-result.quarter_start).le(6*M)]
    return result.copy()
flow.candidate=select
def configure(year):
    f=flow.forward
    if year==2024:
        f.NORM=ROOT/'work'/'breakout_2024_11'/'normalized';warm='2023-12-01';start='2024-01-01';end='2025-01-01'
    elif year==2026:
        f.NORM=ROOT/'work'/'breakout_november_2026'/'normalized';warm='2026-04-01';start='2026-05-01';end='2026-11-13'
    elif year==2023:
        f.NORM=ROOT/'work'/'breakout_2023_11'/'normalized';warm='2022-12-01';start='2023-01-01';end='2024-01-01'
    else:raise ValueError(year)
    f.WARM=int(pd.Timestamp(warm,tz='UTC').timestamp()*1000)
    f.START=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    f.END=int(pd.Timestamp(end,tz='UTC').timestamp()*1000)
    f.GRID=np.arange(f.WARM,f.END,M,dtype=np.int64)
def enrich(signals,norm):
    groups=[]
    for c in signals.contract.unique():
        data=pd.read_parquet(norm/f'{c}_klines.parquet',columns=['ts','quote_volume','taker_buy_quote_volume']).set_index('ts')
        assert data.index.is_unique
        g=signals[signals.contract==c].copy();x=data.reindex(g.break_ts.to_numpy(np.int64))
        v=x.quote_volume.to_numpy(float);b=x.taker_buy_quote_volume.to_numpy(float)
        valid=np.isfinite(v)&np.isfinite(b)&(v>0)&(b>=0)&(b<=v*(1+1e-8))
        imbalance=np.full(len(g),np.nan);imbalance[valid]=g.side.to_numpy()[valid]*(2*b[valid]/v[valid]-1)
        g['signal_minute_imbalance']=imbalance
        g['signal_stop_fraction']=g.side*(g.signal_close-g.stop_price)/g.signal_close
        assert (g.decision_ts==g.break_ts+M).all() and (g.ts==g.decision_ts+M).all()
        groups.append(g)
    result=pd.concat(groups,ignore_index=True).sort_values(['ts','symbol']).reset_index(drop=True)
    assert len(result)==len(signals) and result.observation_id.is_unique
    return result
def get_context(year):
    configure(year);f=flow.forward
    signal_path=(PARENT/'2024反向跨期验证'/'2024因果候选与事后标签.parquet') if year==2024 else (PARENT/'2026因果候选与事后标签.parquet')
    signals=enrich(pd.read_parquet(signal_path),f.NORM)
    signals.to_parquet(HERE/f'{year}新特征与事后标签.parquet',index=False)
    market=f.FixedMarket();guard=f.FixedGuard(market)
    return signals,market,guard
def read_trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    training={};later=[]
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        signals,market,guard=get_context(year)
        for name in NAMES:
            training[(year,name)]=flow.simulate(signals,name,start,end,market,guard,20,'main',period)
        del signals,market,guard;gc.collect()
    summaries=[]
    for name in NAMES:
        a=training[(2024,name)];b=training[(2026,name)]
        trades=read_trades('train_h1_2024',name)+read_trades('train_may_jul_2026',name)
        wins=sum(t['net']>0 for t in trades);gross_win=sum(t['net'] for t in trades if t['net']>0)
        gross_loss=-sum(t['net'] for t in trades if t['net']<0)
        viable=a['valid_for_comparison'] and b['valid_for_comparison'] and a['trades']>=30 and b['trades']>=30
        rate=100*wins/len(trades) if trades else None;pf=gross_win/gross_loss if gross_loss else None
        passed=bool(viable and a['net_pnl']>0 and b['net_pnl']>0 and rate is not None and rate>=60 and pf is not None and pf>1)
        summaries.append({'candidate':name,'viable':viable,'training_pass':passed,
          'h1_2024_trades':a['trades'],'h1_2024_net':a['net_pnl'],'h1_2024_win_rate':a['net_win_rate_pct'],
          'may_jul_2026_trades':b['trades'],'may_jul_2026_net':b['net_pnl'],'may_jul_2026_win_rate':b['net_win_rate_pct'],
          'pooled_trades':len(trades),'pooled_win_rate':rate,'pooled_profit_factor':pf,
          'minimum_period_net':min(a['net_pnl'],b['net_pnl']),'sum_period_net':a['net_pnl']+b['net_pnl']})
    flow.dump(HERE/'训练两期候选汇总.json',summaries)
    viable=[s for s in summaries if s['viable']];passed=[s for s in viable if s['training_pass']]
    chosen=max(passed or viable,key=lambda s:(s['minimum_period_net'],s['sum_period_net'])) if viable else None
    decision={'selected':chosen['candidate'] if chosen else None,'training_success':bool(passed),
       'selected_training_metrics':chosen,
       'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
       'training_sha256':hashlib.sha256((HERE/'训练两期候选汇总.json').read_bytes()).hexdigest(),
       'note':'Frozen before checking the older 2023 period; all other periods were previously explored.'}
    flow.dump(HERE/'第二轮冻结候选.json',decision)
    print('ROUND2_SELECTION',json.dumps(decision,ensure_ascii=False),flush=True)
    if not chosen:return
    for year,periods in [(2024,[('h2_2024','2024-07-01','2024-12-31')]),
                         (2026,[('aug_oct_2026','2026-08-01','2026-10-31'),
                                ('full_2026','2026-05-01','2026-10-31'),
                                ('nov12_2026','2026-11-01','2026-11-12')])]:
        signals,market,guard=get_context(year)
        for label,start,end in periods:
          for lev in (10,20):
           for scenario in ('main','stress','delay1'):
            later.append(flow.simulate(signals,chosen['candidate'],start,end,market,guard,lev,scenario,label))
        del signals,market,guard;gc.collect()
    flow.dump(HERE/'第二轮历史对照.json',later)
    pd.DataFrame(later).to_csv(HERE/'第二轮历史对照.csv',index=False,encoding='utf-8-sig')
    print('ROUND2_DEVELOPMENT_COMPLETE',len(later),flush=True)
if __name__=='__main__':main()
