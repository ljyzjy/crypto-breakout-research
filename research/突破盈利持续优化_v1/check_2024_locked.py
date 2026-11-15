"""Apply the previously frozen training selection to older public history."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import flow_research as flow

HERE=Path(__file__).resolve().parent
selection=json.loads((HERE/'冻结选定候选.json').read_text(encoding='utf-8'))
assert selection['plan_sha256']==hashlib.sha256((HERE/'研究计划与筛选标准.json').read_bytes()).hexdigest()
assert selection['training_results_sha256']==hashlib.sha256((HERE/'训练期全部候选.json').read_bytes()).hexdigest()
assert selection['selected']
selection_hash=hashlib.sha256((HERE/'冻结选定候选.json').read_bytes()).hexdigest()
out=HERE/'2024反向跨期验证';out.mkdir(exist_ok=True)
flow.HERE=out;flow.relaxed.HERE=out;flow.research.HERE=out
forward=flow.forward
forward.NORM=HERE.parent.parent/'work'/'breakout_2024_11'/'normalized'
forward.WARM=int(pd.Timestamp('2023-12-01',tz='UTC').timestamp()*1000)
forward.START=int(pd.Timestamp('2024-01-01',tz='UTC').timestamp()*1000)
forward.END=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
forward.GRID=np.arange(forward.WARM,forward.END,flow.M,dtype=np.int64)
def main():
    market=forward.FixedMarket();guard=forward.FixedGuard(market)
    raw=flow.relaxed.create_signals(market,guard);signals,invalid=flow.enrich_flow(raw,forward.NORM)
    signals.to_parquet(out/'2024因果候选与事后标签.parquet',index=False)
    flow.dump(out/'2024主动成交特征检查.json',{'candidates':len(signals),'invalid_flow_count':len(invalid),
        'invalid_ids':invalid,'selection_sha256':selection_hash,'pool':flow.SYMBOLS})
    periods=[('year_2024','2024-01-01','2024-12-31'),('h1_2024','2024-01-01','2024-06-30'),
             ('h2_2024','2024-07-01','2024-12-31')]
    results=[]
    for tag,start,end in periods:
      for lev in (10,20):
       for scenario in ('main','stress','delay1'):
        results.append(flow.simulate(signals,selection['selected'],start,end,market,guard,lev,scenario,tag))
    flow.dump(out/'2024冻结候选各情景.json',results)
    pd.DataFrame(results).to_csv(out/'2024冻结候选各情景.csv',index=False,encoding='utf-8-sig')
    assert hashlib.sha256((HERE/'冻结选定候选.json').read_bytes()).hexdigest()==selection_hash
    print('LOCKED_2024_TEST_COMPLETE',len(results),'valid',sum(r['valid_for_comparison'] for r in results),flush=True)
if __name__=='__main__':main()
