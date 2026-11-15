"""Predeclared targets with a minimum price room beyond modeled costs."""
import gc,hashlib,json,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(PARENT/'第二轮_成本空间与即时成交'))
sys.path.insert(0,str(PARENT/'第六轮_柱内首次触价'))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch
flow.HERE=HERE;flow.eng=touch.engine
VARIANTS=[('room_half_r',.5),('room_threequarter_r',.75),('room_one_r',1.)]
TARGETS=dict(VARIANTS)
def select(signals,name):
    target=TARGETS[name];est_entry=signals.raw_entry_5s*(1+signals.side*.0005)
    price_risk=signals.side*(est_entry-signals.stop_price)
    mask=np.isfinite(est_entry)&np.isfinite(price_risk)&(price_risk>0)&(target*price_risk/est_entry>=.0035)
    return signals[mask].copy()
flow.candidate=select
def read_trades(period,name):
    return json.loads((HERE/f'{period}_{name}_20x_main_trades.json').read_text(encoding='utf-8'))
def main():
    signals=touch.load_data();training={};results=[]
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','train_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','train_may_jul_2026')]:
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        subset=signals[signals.source_year.eq(str(year))].copy()
        for name,target in VARIANTS:
            for lev,scenario in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
                sm=flow.simulate(subset,name,start,end,market,guard,lev,scenario,period,target_override=target)
                results.append(sm)
                if lev==20 and scenario=='main':training[(year,name)]=sm
        del market,guard,subset;gc.collect()
    scores=[]
    for name,target in VARIANTS:
        a=training[(2024,name)];b=training[(2026,name)]
        comb=read_trades('train_h1_2024',name)+read_trades('train_may_jul_2026',name)
        pos=sum(t['net'] for t in comb if t['net']>0);neg=-sum(t['net'] for t in comb if t['net']<0)
        rate=100*sum(t['net']>0 for t in comb)/len(comb) if comb else None;pf=pos/neg if neg else None
        viable=a['valid_for_comparison'] and b['valid_for_comparison'] and a['trades']>=30 and b['trades']>=30
        passed=bool(viable and a['net_pnl']>0 and b['net_pnl']>0 and rate is not None and rate>=60 and pf is not None and pf>1)
        scores.append({'candidate':name,'target_r':target,'viable':viable,'training_pass':passed,
          'h1_2024_trades':a['trades'],'h1_2024_net':a['net_pnl'],'h1_2024_win_rate':a['net_win_rate_pct'],
          'may_jul_2026_trades':b['trades'],'may_jul_2026_net':b['net_pnl'],'may_jul_2026_win_rate':b['net_win_rate_pct'],
          'pooled_trades':len(comb),'pooled_win_rate':rate,'pooled_profit_factor':pf,
          'minimum_period_net':min(a['net_pnl'],b['net_pnl']),'sum_period_net':a['net_pnl']+b['net_pnl']})
    flow.dump(HERE/'近止盈训练全部账户.json',results);flow.dump(HERE/'近止盈训练候选对照.json',scores)
    viable=[x for x in scores if x['viable']];passed=[x for x in viable if x['training_pass']]
    chosen=max(passed or viable,key=lambda x:(x['minimum_period_net'],x['sum_period_net'])) if viable else None
    decision={'selected':chosen['candidate'] if chosen else None,'target_r':chosen['target_r'] if chosen else None,
      'training_success':bool(passed),'metrics':chosen,
      'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
      'training_sha256':hashlib.sha256((HERE/'近止盈训练候选对照.json').read_bytes()).hexdigest(),
      'limit':'Profit target, stop and all account risk actions are minute based; same-minute stop priority.'}
    flow.dump(HERE/'近止盈冻结候选.json',decision)
    print('ROOM_TRAIN_COMPLETE',json.dumps(decision,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
