"""Frozen completed-minute BTC/ETH lead filters on actual first-touch events."""
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
TOUCH=PARENT/'第六轮_柱内首次触价'
ROUND2=PARENT/'第二轮_成本空间与即时成交'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(ROUND2))
import flow_research as flow
import train_and_compare as r2

def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp)
    sys.modules[name]=m;sp.loader.exec_module(m);return m
flow.eng=load('lead_touch_engine',TOUCH/'touch_engine.py');flow.HERE=HERE
TARGETS=[('btc_align_1r',1.),('btc_eth_align_1r',1.),('btc_lead_1r',1.),
         ('btc_align_2r',2.),('btc_eth_align_2r',2.),('btc_lead_2r',2.)]
def select(signals,name):
    side=signals.side
    if name.startswith('btc_eth_align'):
        mask=(side*signals.btc_prev_return>0)&(side*signals.eth_prev_return>0)
    elif name.startswith('btc_align'):
        mask=side*signals.btc_prev_return>0
    elif name.startswith('btc_lead'):
        mask=side*(signals.btc_prev_return-signals.asset_prev_return)>=.0002
    else:raise ValueError(name)
    return signals[mask].copy()
flow.candidate=select
def enrich(signals,year,tag=None):
    r2.configure(year);norm=flow.forward.NORM
    def close(contract):
        x=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','close']).set_index('ts')
        assert x.index.is_unique
        return x.close
    btc=close('BTCUSDT');eth=close('ETHUSDT');pieces=[];M=60_000
    for contract,g in signals.groupby('contract'):
        a=close(contract);g=g.copy();t=g.trigger_minute.to_numpy('int64')
        def previous(series):
            p1=series.reindex(t-M).to_numpy(float);p2=series.reindex(t-2*M).to_numpy(float)
            return np.divide(p1,p2,out=np.full(len(g),np.nan),where=np.isfinite(p1)&np.isfinite(p2)&(p2>0))-1
        g['btc_prev_return']=previous(btc);g['eth_prev_return']=previous(eth);g['asset_prev_return']=previous(a)
        g['lead_features_known_ts']=g.trigger_minute
        assert (g.lead_features_known_ts<=g.decision_ts).all()
        pieces.append(g)
    out=pd.concat(pieces,ignore_index=True).sort_values(['ts','symbol']).reset_index(drop=True)
    suffix=f'_{tag}' if tag else ''
    out.to_parquet(HERE/f'{year}触价前市场特征{suffix}.parquet',index=False)
    return out
def read_trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    meta=json.loads((TOUCH/'逐笔触价档案校验_训练.json').read_text(encoding='utf-8'))
    assert not meta['archive_errors'] and meta['statuses']=={'verified':251}
    signals=pd.read_parquet(TOUCH/'逐笔首次触价与五秒入场_训练.parquet')
    signals=signals[signals.status.eq('verified')].copy();signals['tick_status']='verified'
    training={}
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        subset=enrich(signals[signals.source_year.eq(str(year))],year)
        market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        for name,target in TARGETS:
            training[(year,name)]=flow.simulate(subset,name,start,end,market,guard,20,'main',period,target_override=target)
        del subset,market,guard;gc.collect()
    scores=[]
    for name,target in TARGETS:
        a=training[(2024,name)];b=training[(2026,name)]
        combined=read_trades('train_h1_2024',name)+read_trades('train_may_jul_2026',name)
        wins=sum(x['net']>0 for x in combined);positive=sum(x['net'] for x in combined if x['net']>0)
        negative=-sum(x['net'] for x in combined if x['net']<0)
        rate=100*wins/len(combined) if combined else None;pf=positive/negative if negative else None
        viable=a['valid_for_comparison'] and b['valid_for_comparison'] and a['trades']>=15 and b['trades']>=15
        passed=bool(viable and a['net_pnl']>0 and b['net_pnl']>0 and rate is not None and rate>=60 and pf is not None and pf>1)
        scores.append({'candidate':name,'target_r':target,'viable':viable,'training_pass':passed,
          'h1_2024_trades':a['trades'],'h1_2024_net':a['net_pnl'],'h1_2024_win_rate':a['net_win_rate_pct'],
          'may_jul_2026_trades':b['trades'],'may_jul_2026_net':b['net_pnl'],'may_jul_2026_win_rate':b['net_win_rate_pct'],
          'pooled_trades':len(combined),'pooled_win_rate':rate,'pooled_profit_factor':pf,
          'minimum_period_net':min(a['net_pnl'],b['net_pnl']),'sum_period_net':a['net_pnl']+b['net_pnl']})
    flow.dump(HERE/'短时领先训练候选对照.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    frozen={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
            'training_success':bool(passed),'metrics':chosen,
            'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
            'training_sha256':hashlib.sha256((HERE/'短时领先训练候选对照.json').read_bytes()).hexdigest(),
            'limit':'15-trade floor is only for exploratory selection; no final 100-trade standard was relaxed.'}
    flow.dump(HERE/'短时领先冻结候选.json',frozen)
    print('LEAD_FILTER_TRAIN_COMPLETE',json.dumps(frozen,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
