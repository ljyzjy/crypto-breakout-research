"""Predeclared intraminute first-touch training; no account/order access."""
import gc
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROUND2=PARENT/'第二轮_成本空间与即时成交'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(ROUND2))
import flow_research as flow
import train_and_compare as r2

def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp)
    sys.modules[name]=m;sp.loader.exec_module(m);return m
engine=load('intraminute_engine',HERE/'touch_engine.py')
flow.HERE=HERE;flow.eng=engine;flow.candidate=lambda signals,name:signals.copy()
TARGETS=[('touch_1r',1.),('touch_2r',2.),('touch_3r',3.)]
def load_data():
    meta=json.loads((HERE/'逐笔触价档案校验_训练.json').read_text(encoding='utf-8'))
    fatal={'archive_error','no_trigger_data','ohlc_trade_mismatch','no_price_reference',
           'no_price_before_candle_end','minute_archive_mismatch'}
    if meta['archive_errors'] or any(meta['statuses'].get(x,0) for x in fatal):raise ValueError('first_touch_source_incomplete')
    allrows=pd.read_parquet(HERE/'逐笔首次触价与五秒入场_训练.parquet')
    signals=allrows[allrows.status.eq('verified')].copy()
    signals['tick_status']='verified'
    assert signals.observation_id.is_unique
    assert (signals.entry_exec_ts>=signals.decision_ts+5000).all()
    assert (signals.entry_exec_ts<signals.quarter_end).all()
    assert (signals.feature_known_ts<=signals.decision_ts).all()
    return signals
def read_trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    signals=load_data();training={}
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        subset=signals[signals.source_year.eq(str(year))].copy()
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
        viable=a['valid_for_comparison'] and b['valid_for_comparison'] and a['trades']>=30 and b['trades']>=30
        passed=bool(viable and a['net_pnl']>0 and b['net_pnl']>0 and rate is not None and rate>=60 and pf is not None and pf>1)
        scores.append({'candidate':name,'target_r':target,'viable':viable,'training_pass':passed,
          'h1_2024_trades':a['trades'],'h1_2024_net':a['net_pnl'],'h1_2024_win_rate':a['net_win_rate_pct'],
          'may_jul_2026_trades':b['trades'],'may_jul_2026_net':b['net_pnl'],'may_jul_2026_win_rate':b['net_win_rate_pct'],
          'pooled_trades':len(combined),'pooled_win_rate':rate,'pooled_profit_factor':pf,
          'minimum_period_net':min(a['net_pnl'],b['net_pnl']),'sum_period_net':a['net_pnl']+b['net_pnl']})
    flow.dump(HERE/'柱内触价训练候选对照.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    report={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
            'training_success':bool(passed),'metrics':chosen,
            'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
            'training_sha256':hashlib.sha256((HERE/'柱内触价训练候选对照.json').read_bytes()).hexdigest(),
            'limit':'5s public-trade reference and minute-level exits; account decisions within each minute are approximate.'}
    flow.dump(HERE/'柱内触价冻结候选.json',report)
    print('INTRAMINUTE_TRAIN_COMPLETE',json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
