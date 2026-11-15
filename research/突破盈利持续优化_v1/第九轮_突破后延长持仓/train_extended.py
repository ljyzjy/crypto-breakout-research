"""Train frozen overnight 4h/12h exits on the first-touch signal family."""
import gc
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
R2=PARENT/'第二轮_成本空间与即时成交';R6=PARENT/'第六轮_柱内首次触价'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(R2));sys.path.insert(0,str(R6))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch

def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp)
    sys.modules[name]=m;sp.loader.exec_module(m);return m
engine=load('extended_model_engine',HERE/'extended_engine.py')
flow.HERE=HERE;flow.eng=engine;flow.candidate=lambda s,n:s.copy()
VARIANTS=[('h4_1r',240,1.),('h4_2r',240,2.),('h4_3r',240,3.),
          ('h12_1r',720,1.),('h12_2r',720,2.),('h12_3r',720,3.)]
def trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    signals=touch.load_data();training={}
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        subset=signals[signals.source_year.eq(str(year))].copy()
        for name,hold,target in VARIANTS:
            training[(year,name)]=flow.simulate(subset,name,start,end,market,guard,20,'main',period,
                                               target_override=target,max_hold_minutes=hold,allow_overnight=True)
        del market,guard,subset;gc.collect()
    scores=[]
    for name,hold,target in VARIANTS:
        a=training[(2024,name)];b=training[(2026,name)]
        combined=trades('train_h1_2024',name)+trades('train_may_jul_2026',name)
        wins=sum(x['net']>0 for x in combined);positive=sum(x['net'] for x in combined if x['net']>0)
        negative=-sum(x['net'] for x in combined if x['net']<0)
        rate=100*wins/len(combined) if combined else None;pf=positive/negative if negative else None
        viable=a['valid_for_comparison'] and b['valid_for_comparison'] and a['trades']>=30 and b['trades']>=30
        passed=bool(viable and a['net_pnl']>0 and b['net_pnl']>0 and rate is not None and rate>=60 and pf is not None and pf>1)
        scores.append({'candidate':name,'target_r':target,'max_hold_minutes':hold,'viable':viable,'training_pass':passed,
          'h1_2024_trades':a['trades'],'h1_2024_net':a['net_pnl'],'h1_2024_win_rate':a['net_win_rate_pct'],
          'may_jul_2026_trades':b['trades'],'may_jul_2026_net':b['net_pnl'],'may_jul_2026_win_rate':b['net_win_rate_pct'],
          'pooled_trades':len(combined),'pooled_win_rate':rate,'pooled_profit_factor':pf,
          'minimum_period_net':min(a['net_pnl'],b['net_pnl']),'sum_period_net':a['net_pnl']+b['net_pnl'],
          'h1_2024_funding':a['funding_cost'],'may_jul_2026_funding':b['funding_cost']})
    flow.dump(HERE/'延长持仓训练候选对照.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    decision={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
              'max_hold_minutes':chosen['max_hold_minutes'] if chosen else None,'training_success':bool(passed),'metrics':chosen,
              'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
              'training_sha256':hashlib.sha256((HERE/'延长持仓训练候选对照.json').read_bytes()).hexdigest(),
              'limit':'Entry uses 5s public-trade reference; exits, liquidation proxy and account protection remain minute-level.'}
    flow.dump(HERE/'延长持仓冻结候选.json',decision)
    print('EXTENDED_TRAIN_COMPLETE',json.dumps(decision,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
