"""Recompute market-order accounts under fixed positive slippage scenarios."""
import gc,hashlib,json,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
base=flow.load('sensitivity_partial_engine',PARENT/'第十二轮_分批保护'/'partial_engine.py')
class CostEngine:
    def __init__(self,slippage):self.slippage=slippage
    def simulate(self,sc,*args,**kwargs):
        scenario={**sc,'slippage':self.slippage}
        return base.simulate(scenario,*args,**kwargs)
flow.HERE=HERE
flow.candidate=lambda s,n:s[s.flow_status.eq('verified')&s.flow_count.ge(3)&s.directional_imbalance.ge(.1)&
                              (s.side*(s.raw_entry_5s-s.level)>0)].copy()
def load_data():
    src=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
    src=src[src.status.eq('verified')].copy();src['tick_status']='verified'
    ft=pd.concat([pd.read_parquet(PARENT/'第二十二轮_五秒成交跨期探索'/'五秒主动成交特征_2024.parquet'),
                  pd.read_parquet(PARENT/'第十九轮_突破后五秒主动成交'/'五秒主动成交特征_2026.parquet')],ignore_index=True)
    ft=ft.rename(columns={'status':'flow_status','count':'flow_count','archive_sha256':'flow_sha'})
    d=src.merge(ft,on='observation_id',validate='one_to_one');assert len(d)==len(src)==len(ft)
    good=d[d.flow_status.eq('verified')]
    assert (good.flow_sha==good.archive_sha256).all() and (good.last_ts<good.window_end).all() and (good.window_end<=good.entry_exec_ts).all()
    return d
def main():
    sig=load_data();results=[]
    for year,start,end,tag in [(2024,'2024-01-01','2024-06-30','h1_2024'),(2026,'2026-05-01','2026-07-31','may_jul_2026')]:
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        data=sig[sig.source_year.eq(str(year))].copy()
        for bps,slip in [(2,.0002),(5,.0005),(10,.001)]:
            flow.eng=CostEngine(slip)
            for name,target,partial in [('fixed_1r',1.,False),('fixed_partial_2r',2.,True)]:
              for lev in (10,20):
                period=f'slip{bps}bp_{tag}'
                sm=flow.simulate(data,name,start,end,market,guard,lev,'main',period,target_override=target,partial_exit=partial)
                assert sm['fee']==.0005 and sm['slippage']==slip
                results.append(sm)
        del market,guard,data;gc.collect()
    flow.dump(HERE/'滑点情景全部账户.json',results)
    fields=['period','run_id','position_leverage','fee','slippage','trades','active_calendar_days','net_win_rate_pct',
            'net_pnl','profit_factor','max_drawdown','acceptance_pass','valid_for_comparison']
    pd.DataFrame([{k:s.get(k) for k in fields} for s in results]).to_csv(HERE/'市价滑点情景对照.csv',index=False,encoding='utf-8-sig')
    flow.dump(HERE/'敏感性说明.json',{'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
       'accounts':len(results),'all_valid':all(s['valid_for_comparison'] for s in results),
       'note':'Counterfactual slippage assumptions; 2bp is not a verified obtainable fill.'})
    print('COST_SENSITIVITY_COMPLETE',len(results),'valid',sum(s['valid_for_comparison'] for s in results),flush=True)
if __name__=='__main__':main()
