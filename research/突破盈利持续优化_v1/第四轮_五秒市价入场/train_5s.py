"""Select one 5-second-entry candidate using predeclared training windows only."""
import gc
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROOT=HERE.parent.parent.parent
ROUND2=PARENT/'第二轮_成本空间与即时成交'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(ROUND2))
import flow_research as flow
import train_and_compare as r2

def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp)
    sys.modules[name]=m;sp.loader.exec_module(m);return m
tick=load('five_second_engine',HERE/'tick_entry_engine.py')
flow.HERE=HERE;flow.eng=tick;flow.candidate=lambda signals,name:signals.copy()
TARGETS=[('second_1r',1.),('second_1_5r',1.5),('second_2r',2.)]
M=60_000
def load_signals(year,phase):
    r2.configure(year)
    source=(HERE/'2023因果候选与事后标签.parquet') if year==2023 else (ROUND2/f'{year}新特征与事后标签.parquet')
    signals=pd.read_parquet(source)
    ticks=pd.read_parquet(HERE/f'五秒价格摘要_{phase}.parquet')
    cols=['observation_id','status','entry_exec_ts','raw_entry_5s','suffix_high','suffix_low','suffix_close']
    ticks=ticks[cols].rename(columns={'status':'tick_status'})
    signals=signals.merge(ticks,on='observation_id',how='left',validate='one_to_one')
    signals['tick_status']=signals.tick_status.fillna('not_requested_outside_phase')
    signals['ts']=signals.decision_ts
    return signals
def ensure_data(signals,start,end):
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000);hi=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    d=signals[signals.decision_ts.ge(lo)&signals.decision_ts.lt(hi)].copy()
    d=d[((d.decision_ts//M+480)%1440)<1320]
    bad=d[~d.tick_status.eq('verified')]
    if len(bad):raise ValueError(f'tick_data_incomplete:{len(bad)}')
    assert (d.entry_exec_ts>=d.decision_ts+5000).all() and (d.entry_exec_ts<d.decision_ts+M).all()
def context(year,phase,start,end):
    signals=load_signals(year,phase);ensure_data(signals,start,end)
    market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    return signals,market,guard
def trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    training={}
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        signals,market,guard=context(year,'train',start,end)
        for name,target in TARGETS:
            training[(year,name)]=flow.simulate(signals,name,start,end,market,guard,20,'main',period,target_override=target)
        del signals,market,guard;gc.collect()
    scores=[]
    for name,target in TARGETS:
        a=training[(2024,name)];b=training[(2026,name)]
        combined=trades('train_h1_2024',name)+trades('train_may_jul_2026',name)
        wins=sum(x['net']>0 for x in combined);positive=sum(x['net'] for x in combined if x['net']>0)
        negative=-sum(x['net'] for x in combined if x['net']<0)
        rate=100*wins/len(combined) if combined else None;pf=positive/negative if negative else None
        viable=a['valid_for_comparison'] and b['valid_for_comparison'] and a['trades']>=30 and b['trades']>=30
        passed=bool(viable and a['net_pnl']>0 and b['net_pnl']>0 and rate is not None and rate>=60 and pf is not None and pf>1)
        scores.append({'candidate':name,'target_r':target,'viable':viable,'training_pass':passed,
          'h1_2024_trades':a['trades'],'h1_2024_net':a['net_pnl'],'h1_2024_win_rate':a['net_win_rate_pct'],
          'may_jul_2026_trades':b['trades'],'may_jul_2026_net':b['net_pnl'],'may_jul_2026_win_rate':b['net_win_rate_pct'],
          'pooled_trades':len(combined),'pooled_win_rate':rate,'pooled_profit_factor':pf,
          'minimum_period_net':min(a['net_pnl'],b['net_pnl']),'sum_period_net':a['net_pnl']+b['net_pnl']})
    flow.dump(HERE/'五秒训练候选对比.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    frozen={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
            'training_success':bool(passed),'metrics':chosen,
            'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
            'training_sha256':hashlib.sha256((HERE/'五秒训练候选对比.json').read_bytes()).hexdigest(),
            'note':'The 5s entry price is a public trade plus assumed slippage; subsequent exits remain minute-level.'}
    flow.dump(HERE/'五秒冻结候选.json',frozen)
    print('FIVE_SECOND_LOCKED',json.dumps(frozen,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
