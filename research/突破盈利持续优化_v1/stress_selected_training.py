"""Run predeclared higher-fee and stop-shock scenarios on locked candidates."""
import gc
import json
import sys
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
R2=HERE/'第二轮_成本空间与即时成交'
R4=HERE/'第四轮_五秒市价入场'
R5=HERE/'第五轮_五秒波动与成本空间'
R6=HERE/'第六轮_柱内首次触价'
R8=HERE/'第八轮_BTC短时领先'
for p in [HERE,R2,R4,R5,R8]:sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_5s as fast
import train_volatility as vol
import train_lead as lead

MODELS=[('five_second',R4,'五秒冻结候选.json',fast.tick,lambda s,n:s.copy()),
        ('volatility',R5,'波动筛选冻结候选.json',fast.tick,vol.select),
        ('first_touch',R6,'柱内触价冻结候选.json',lead.flow.eng,lambda s,n:s.copy()),
        ('btc_eth',R8,'短时领先冻结候选.json',lead.flow.eng,lead.select)]
def main():
    results=[]
    for year,start,end,period in [(2024,'2024-01-01','2024-06-30','stress_h1_2024'),
                                  (2026,'2026-05-01','2026-07-31','stress_may_jul_2026')]:
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        close_sig=fast.load_signals(year,'train');fast.ensure_data(close_sig,start,end)
        touch_sig=pd.read_parquet(R6/'逐笔首次触价与五秒入场_训练.parquet')
        touch_sig=touch_sig[touch_sig.status.eq('verified') & touch_sig.source_year.eq(str(year))].copy()
        touch_sig['tick_status']='verified'
        lead_sig=pd.read_parquet(R8/f'{year}触价前市场特征.parquet')
        for kind,directory,file,engine,selector in MODELS:
            chosen=json.loads((directory/file).read_text(encoding='utf-8'))
            if not chosen['selected']:continue
            flow.HERE=directory;flow.eng=engine;flow.candidate=selector
            sig=close_sig if kind in ('five_second','volatility') else (touch_sig if kind=='first_touch' else lead_sig)
            for lev in (10,20):
                sm=flow.simulate(sig,chosen['selected'],start,end,market,guard,lev,'stress',period,target_override=chosen['target_r'])
                sm['model']=kind;results.append(sm)
        del market,guard,close_sig,touch_sig,lead_sig;gc.collect()
    flow.dump(HERE/'已选候选训练期压力结果.json',results)
    pd.DataFrame(results).to_csv(HERE/'已选候选训练期压力结果.csv',index=False,encoding='utf-8-sig')
    print('TRAINING_STRESS_COMPLETE',len(results),'valid',sum(x['valid_for_comparison'] for x in results),flush=True)
if __name__=='__main__':main()
