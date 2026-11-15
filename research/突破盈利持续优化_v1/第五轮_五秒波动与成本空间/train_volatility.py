"""Frozen 5-second volatility and cost-room hypothesis training."""
import gc
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROUND4=PARENT/'第四轮_五秒市价入场'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(ROUND4))
import train_5s as base

flow=base.flow;flow.HERE=HERE
TARGETS=[('vol_1r',1.),('vol_2r',2.),('vol_ne_1r',1.),('vol_ne_2r',2.),
         ('vol_room_1r',1.),('vol_room_2r',2.)]
def select(signals,name):
    out=signals[(signals.atr/signals.signal_close).ge(.005)]
    if '_ne_' in name:out=out[out.partial_body_atr.le(1.)]
    if '_room_' in name:out=out[out.signal_stop_fraction.ge(.0045)]
    return out.copy()
flow.candidate=select
def trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    training={}
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        signals,market,guard=base.context(year,'train',start,end)
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
    flow.dump(HERE/'波动筛选训练候选对照.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    frozen={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
            'training_success':bool(passed),'metrics':chosen,
            'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
            'training_sha256':hashlib.sha256((HERE/'波动筛选训练候选对照.json').read_bytes()).hexdigest(),
            'note':'Predeclared thresholds; 5s public-trade reference, subsequent exit only minute-level.'}
    flow.dump(HERE/'波动筛选冻结候选.json',frozen)
    print('VOLATILITY_FROZEN',json.dumps(frozen,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
