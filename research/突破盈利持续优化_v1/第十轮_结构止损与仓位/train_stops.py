"""Frozen wider stops using exclusively already-completed pre-trigger minutes."""
import gc
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
R2=PARENT/'第二轮_成本空间与即时成交';R6=PARENT/'第六轮_柱内首次触价';R9=PARENT/'第九轮_突破后延长持仓'
for p in (PARENT,R2,R6,R9):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch
import train_extended as extended

flow.HERE=HERE;flow.eng=extended.engine
VARIANTS=[('prefix_1r',1.),('prefix_2r',2.),('prefix_3r',3.),
          ('atr_1r',1.),('atr_2r',2.),('atr_3r',3.)]
M=60_000
def select(signals,name):
    out=signals.copy()
    out['stop_price']=out.prefix_stop if name.startswith('prefix_') else out.atr_stop
    return out
flow.candidate=select
def enrich(signals,year,tag='train'):
    r2.configure(year);norm=flow.forward.NORM;pieces=[]
    for c,g in signals.groupby('contract'):
        raw=pd.read_parquet(norm/f'{c}_klines.parquet',columns=['ts','high','low']).set_index('ts')
        assert raw.index.is_unique
        g=g.copy();prefix=[]
        for r in g.itertuples(index=False):
            times=np.arange(int(r.quarter_start),int(r.trigger_minute),M,dtype=np.int64)
            d=raw.reindex(times);assert len(d)>0 and np.isfinite(d.to_numpy(float)).all()
            stop=float(d.low.min()-.1*r.atr if int(r.side)==1 else d.high.max()+.1*r.atr)
            prefix.append(stop)
        g['prefix_stop']=prefix;g['atr_stop']=g.level-g.side*g.atr
        assert (g.feature_known_ts<=g.decision_ts).all()
        pieces.append(g)
    out=pd.concat(pieces,ignore_index=True).sort_values(['ts','symbol']).reset_index(drop=True)
    out.to_parquet(HERE/f'{year}结构止损特征_{tag}.parquet',index=False)
    return out
def trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    signals=touch.load_data();training={}
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        subset=enrich(signals[signals.source_year.eq(str(year))],year)
        market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        for name,target in VARIANTS:
            training[(year,name)]=flow.simulate(subset,name,start,end,market,guard,20,'main',period,
                                               target_override=target,max_hold_minutes=240,allow_overnight=True)
        del market,guard,subset;gc.collect()
    scores=[]
    for name,target in VARIANTS:
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
    flow.dump(HERE/'结构止损训练候选对照.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    frozen={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
            'max_hold_minutes':240,'training_success':bool(passed),'metrics':chosen,
            'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
            'training_sha256':hashlib.sha256((HERE/'结构止损训练候选对照.json').read_bytes()).hexdigest(),
            'limit':'Wider stop does not guarantee controlled loss; entry is tick-reference and later exits are minute-level.'}
    flow.dump(HERE/'结构止损冻结候选.json',frozen)
    print('STRUCTURAL_STOP_TRAIN_COMPLETE',json.dumps(frozen,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
