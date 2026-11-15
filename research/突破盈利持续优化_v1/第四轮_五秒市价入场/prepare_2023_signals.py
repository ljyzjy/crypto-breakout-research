"""Generate causal older-year candidate times; no strategy outcome evaluation."""
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROUND2=PARENT/'第二轮_成本空间与即时成交'
sys.path.insert(0,str(PARENT));sys.path.insert(0,str(ROUND2))
import flow_research as flow
import train_and_compare as r2

repair=json.loads((ROUND2/'2023日档修复记录.json').read_text(encoding='utf-8'))
assert repair['repaired_contracts']==11 and repair['repaired_minutes']==11*1440
r2.configure(2023)
flow.relaxed.HERE=HERE;flow.research.HERE=HERE
def main():
    market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    first=flow.relaxed.create_signals(market,guard)
    enriched,invalid=flow.enrich_flow(first,flow.forward.NORM)
    enriched=r2.enrich(enriched,flow.forward.NORM)
    enriched.to_parquet(HERE/'2023因果候选与事后标签.parquet',index=False)
    flow.dump(HERE/'2023信号数据状态.json',{'signals':len(enriched),'invalid_flow':len(invalid),
       'mark_gaps':{k:v['mark_missing_in_test'] for k,v in market.minute_quality.items()},
       'no_strategy_outcomes_calculated':True})
    print('OLD_YEAR_SIGNAL_TIMES_READY',len(enriched),'invalid_flow',len(invalid),flush=True)
if __name__=='__main__':main()
