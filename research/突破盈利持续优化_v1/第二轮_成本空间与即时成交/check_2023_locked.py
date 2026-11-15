"""Evaluate only the already-selected minute strategy on older 2023 data."""
import hashlib
import json
from pathlib import Path

import pandas as pd

import train_and_compare as r2

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
flow=r2.flow
selection=json.loads((HERE/'第二轮冻结候选.json').read_text(encoding='utf-8'))
assert selection['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert selection['training_sha256']==hashlib.sha256((HERE/'训练两期候选汇总.json').read_bytes()).hexdigest()
assert selection['selected']
out=HERE/'2023反向跨期验证';out.mkdir(exist_ok=True);flow.HERE=out
r2.configure(2023)
signal_path=PARENT/'第四轮_五秒市价入场'/'2023因果候选与事后标签.parquet'
signals=pd.read_parquet(signal_path)
def main():
    market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    periods=[('year_2023','2023-01-01','2023-12-31'),('h1_2023','2023-01-01','2023-06-30'),
             ('h2_2023','2023-07-01','2023-12-31')]
    results=[]
    for label,start,end in periods:
      for lev in (10,20):
       for scenario in ('main','stress','delay1'):
        results.append(flow.simulate(signals,selection['selected'],start,end,market,guard,lev,scenario,label))
    flow.dump(out/'2023冻结候选各情景.json',results)
    pd.DataFrame(results).to_csv(out/'2023冻结候选各情景.csv',index=False,encoding='utf-8-sig')
    print('ROUND2_2023_COMPLETE',len(results),'valid',sum(x['valid_for_comparison'] for x in results),flush=True)
if __name__=='__main__':main()
