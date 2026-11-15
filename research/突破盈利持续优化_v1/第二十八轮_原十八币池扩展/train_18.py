"""Train/diagnose an 18-pool breakout using verified 5s trade flow."""
import gc,hashlib,importlib.util,json,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
spec=importlib.util.spec_from_file_location('expanded18_configuration',HERE/'generate_18_candidates.py')
config=importlib.util.module_from_spec(spec);sys.modules[spec.name]=config;spec.loader.exec_module(config)
flow.HERE=HERE;flow.eng=flow.load('expanded18_partial_engine',PARENT/'第十二轮_分批保护'/'partial_engine.py')
VARIANTS=[('pool18_flow_1r',1.,False),('pool18_flow_partial_2r',2.,True)]
def select(s,name):
    return s[s.five_status.eq('verified')&s.five_count.ge(3)&s.five_imbalance.ge(.1)&
             (s.side*(s.raw_entry_5s-s.level)>0)].copy()
flow.candidate=select
def load():
    meta=json.loads((HERE/'十八币逐笔核验清单.json').read_text(encoding='utf-8'))
    fatal={'archive_error','no_trigger_data','ohlc_trade_mismatch','no_price_reference','no_price_before_candle_end',
           'minute_archive_mismatch','missing_completed_candle'}
    if meta['archive_errors'] or any(meta['statuses'].get(x,0) for x in fatal):raise ValueError('expanded18_tape_incomplete')
    s=pd.read_parquet(HERE/'十八币首次触价五秒成交.parquet');s=s[s.status.eq('verified')].copy();s['tick_status']='verified'
    assert s.observation_id.is_unique and not s.duplicated(['symbol','quarter_start']).any()
    assert (s.entry_exec_ts>=s.decision_ts+5000).all() and (s.entry_exec_ts<s.quarter_end).all()
    return s
def main():
    s=load();r2.configure(2024);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    subset=s[s.source_year.eq('2024')].copy();training=[]
    for name,target,partial in VARIANTS:
        sm=flow.simulate(subset,name,'2024-01-01','2024-04-30',market,guard,20,'main','train_jan_apr_2024',
                         target_override=target,partial_exit=partial)
        training.append(sm)
    flow.dump(HERE/'十八币训练候选.json',training)
    viable=[v for v in training if v['valid_for_comparison'] and v['trades']>=30]
    passed=[v for v in viable if v['net_win_rate_pct'] is not None and v['net_win_rate_pct']>=60 and v['net_pnl']>0 and
            v['profit_factor'] is not None and v['profit_factor']>1]
    chosen=max(passed or viable,key=lambda v:v['net_pnl']) if viable else None
    item=next((v for v in VARIANTS if chosen and v[0]==chosen['run_id']),None)
    decision={'selected':item[0] if item else None,'target_r':item[1] if item else None,'partial_exit':item[2] if item else None,
      'training_passed':bool(passed),'metrics':{k:chosen.get(k) for k in ['trades','active_calendar_days','net_win_rate_pct','net_pnl','profit_factor','max_drawdown']} if chosen else None,
      'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
      'training_sha256':hashlib.sha256((HERE/'十八币训练候选.json').read_bytes()).hexdigest(),
      'note':'Unpassed training produces diagnostic only; pool is retrospective and 2024/2026 were previously researched.'}
    flow.dump(HERE/'十八币冻结决定.json',decision)
    print('EXPANDED18_SELECTED',json.dumps(decision,ensure_ascii=False),flush=True)
    if not item:return
    validations=[]
    for year,start,end,period in [(2024,'2024-05-01','2024-06-29','validation_may_jun_2024'),
                                  (2026,'2026-05-01','2026-07-31','research_may_jul_2026')]:
        if year!=2024:
            del market,guard;gc.collect();r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        subset=s[s.source_year.eq(str(year))].copy()
        if year==2024:
            lo=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000);subset=subset[subset.decision_ts.ge(lo)].copy()
        for lev,cost in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
            validations.append(flow.simulate(subset,item[0],start,end,market,guard,lev,cost,period,
                                            target_override=item[1],partial_exit=item[2]))
    assert hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()==decision['plan_sha256']
    assert hashlib.sha256((HERE/'十八币训练候选.json').read_bytes()).hexdigest()==decision['training_sha256']
    flow.dump(HERE/'十八币后续账户.json',validations)
    fields=['period','run_id','position_leverage','scenario','trades','active_calendar_days','net_win_rate_pct','net_pnl',
            'profit_factor','max_drawdown','liquidation_proxy_count','valid_for_comparison','issues','acceptance_pass']
    pd.DataFrame([{k:r.get(k) for k in fields} for r in training+validations]).to_csv(HERE/'十八币账户对照.csv',index=False,encoding='utf-8-sig')
    print('EXPANDED18_COMPLETE',len(validations),'valid',sum(v['valid_for_comparison'] for v in validations),flush=True)
if __name__=='__main__':main()
