"""Replay both frozen first-touch candidates on later and older history."""
import gc
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROUND2=PARENT/'第二轮_成本空间与即时成交'
LEAD=PARENT/'第八轮_BTC短时领先'
EXTENDED=PARENT/'第九轮_突破后延长持仓'
STOPS=PARENT/'第十轮_结构止损与仓位'
for p in (PARENT,ROUND2,HERE,LEAD,EXTENDED,STOPS):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_lead as lead
import train_touch as touch
import train_extended as extended
import train_stops as stops

fatal={'archive_error','no_trigger_data','ohlc_trade_mismatch','no_price_reference',
       'no_price_before_candle_end','minute_archive_mismatch'}
def verified(label):
    meta=json.loads((HERE/f'逐笔触价档案校验_{label}.json').read_text(encoding='utf-8'))
    if meta['archive_errors'] or any(meta['statuses'].get(x,0) for x in fatal):raise ValueError(f'{label}_source_incomplete')
    d=pd.read_parquet(HERE/f'逐笔首次触价与五秒入场_{label}.parquet')
    d=d[d.status.eq('verified')].copy();d['tick_status']='verified'
    assert d.observation_id.is_unique and (d.entry_exec_ts>=d.decision_ts+5000).all()
    return d
def decision(path,plan,training):
    x=json.loads(path.read_text(encoding='utf-8'))
    assert x['selected'] and x['plan_sha256']==hashlib.sha256(plan.read_bytes()).hexdigest()
    assert x['training_sha256']==hashlib.sha256(training.read_bytes()).hexdigest()
    return x
def main():
    models=[('touch',HERE,decision(HERE/'柱内触价冻结候选.json',HERE/'冻结研究计划.json',HERE/'柱内触价训练候选对照.json'),touch.engine,lambda s,n:s.copy(),60,False),
            ('lead',LEAD,decision(LEAD/'短时领先冻结候选.json',LEAD/'冻结研究计划.json',LEAD/'短时领先训练候选对照.json'),touch.engine,lead.select,60,False),
            ('extended',EXTENDED,decision(EXTENDED/'延长持仓冻结候选.json',EXTENDED/'冻结研究计划.json',EXTENDED/'延长持仓训练候选对照.json'),extended.engine,lambda s,n:s.copy(),None,True),
            ('stops',STOPS,decision(STOPS/'结构止损冻结候选.json',STOPS/'冻结研究计划.json',STOPS/'结构止损训练候选对照.json'),extended.engine,stops.select,240,True)]
    later=verified('后续');older=verified('2023');results=[]
    periods=[(2024,later,'h2_2024','2024-07-01','2024-12-31'),
             (2026,later,'aug_oct_2026','2026-08-01','2026-10-31'),
             (2026,later,'nov12_2026','2026-11-01','2026-11-12'),
             (2023,older,'year_2023','2023-01-01','2023-12-31'),
             (2023,older,'h1_2023','2023-01-01','2023-06-30'),
             (2023,older,'h2_2023','2023-07-01','2023-12-31')]
    for year,data,period,start,end in periods:
        r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        raw=data[data.source_year.eq(str(year))].copy()
        lead_signals=lead.enrich(raw,year,tag='later')
        stop_signals=stops.enrich(raw,year,tag='later')
        for kind,model_dir,chosen,engine,selector,hold,overnight in models:
            out=model_dir/'冻结候选历史对照';out.mkdir(exist_ok=True)
            flow.HERE=out;flow.eng=engine;flow.candidate=selector
            sig=lead_signals if kind=='lead' else stop_signals if kind=='stops' else raw
            max_hold=chosen.get('max_hold_minutes',60) if hold is None else hold
            for lev in (10,20):
             for scenario in ('main','stress'):
                sm=flow.simulate(sig,chosen['selected'],start,end,market,guard,lev,scenario,period,
                                 target_override=chosen['target_r'],max_hold_minutes=max_hold,allow_overnight=overnight)
                sm['model']=kind;results.append(sm)
        del raw,lead_signals,stop_signals,market,guard;gc.collect()
    flow.dump(HERE/'四种触价方案历史对照.json',results)
    pd.DataFrame(results).to_csv(HERE/'四种触价方案历史对照.csv',index=False,encoding='utf-8-sig')
    print('TOUCH_LATER_FROZEN_COMPLETE',len(results),'valid',sum(x['valid_for_comparison'] for x in results),flush=True)
if __name__=='__main__':main()
