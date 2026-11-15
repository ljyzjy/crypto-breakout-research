"""Predeclared 5-second aggressive-trade filters across both trigger cohorts."""
import gc,hashlib,json,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
flow.HERE=HERE;flow.eng=flow.load('allflow_partial_engine',PARENT/'第十二轮_分批保护'/'partial_engine.py')
VARIANTS=[('allflow_strong_1r',1.,False),('allflow_strong_preflow_1r',1.,False),('allflow_strong_preflow_follow_1r',1.,False),
          ('allflow_strong_partial_2r',2.,True),('allflow_strong_preflow_partial_2r',2.,True),('allflow_strong_preflow_follow_partial_2r',2.,True)]
def select(s,name):
    mask=s.five_status.eq('verified')&s.five_count.ge(3)&s.five_imbalance.ge(.1)&(s.side*(s.raw_entry_5s-s.level)>0)
    if '_preflow_' in name:mask &= s.previous_signed_flow.ge(.1)
    if '_follow_' in name:mask &= s.side*(s.raw_entry_5s-s.signal_close)>0
    return s[mask].copy()
flow.candidate=select
def load_data():
    meta=json.loads((HERE/'五秒主动成交档案校验.json').read_text(encoding='utf-8'))
    if meta['archive_errors']:raise RuntimeError('later_flow_archive_incomplete')
    d=pd.read_parquet(PARENT/'第二十五轮_突破时段扩展'/'合并候选与事前主动成交.parquet')
    feat=pd.concat([pd.read_parquet(PARENT/'第二十二轮_五秒成交跨期探索'/'五秒主动成交特征_2024.parquet'),
                    pd.read_parquet(PARENT/'第十九轮_突破后五秒主动成交'/'五秒主动成交特征_2026.parquet'),
                    pd.read_parquet(HERE/'后续分钟五秒主动成交特征.parquet')],ignore_index=True)
    feat=feat.rename(columns={'status':'five_status','count':'five_count','directional_imbalance':'five_imbalance','archive_sha256':'flow_archive_sha'})
    assert d.observation_id.is_unique and feat.observation_id.is_unique
    s=d.merge(feat,on='observation_id',validate='one_to_one');assert len(s)==len(d)==len(feat)
    good=s[s.five_status.eq('verified')]
    assert (good.flow_archive_sha==good.archive_sha256).all()
    assert (good.first_ts>good.decision_ts).all() and (good.last_ts<good.window_end).all() and (good.window_end<=good.entry_exec_ts).all()
    s.to_parquet(HERE/'全时段五秒特征候选.parquet',index=False)
    quality={'events':len(s),'status_counts':s.five_status.value_counts().to_dict(),
             'at_least_three':int(s.five_count.ge(3).sum()),'cohort_counts':s.cohort.value_counts().to_dict()}
    flow.dump(HERE/'全时段五秒特征质量.json',quality)
    print('ALLFLOW_DATA_READY',json.dumps(quality,ensure_ascii=False),flush=True);return s
def main():
    s=load_data();r2.configure(2024);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    train=s[s.source_year.eq('2024')].copy();results=[]
    for name,target,partial in VARIANTS:
        results.append(flow.simulate(train,name,'2024-01-01','2024-04-30',market,guard,20,'main','train_jan_apr_2024',
                                    target_override=target,partial_exit=partial))
    flow.dump(HERE/'前四月训练候选.json',results)
    viable=[v for v in results if v['valid_for_comparison'] and v['trades']>=30]
    passed=[v for v in viable if v['net_win_rate_pct'] is not None and v['net_win_rate_pct']>=60 and v['net_pnl']>0 and v['profit_factor'] is not None and v['profit_factor']>1]
    chosen=max(passed or viable,key=lambda v:v['net_pnl']) if viable else None
    spec=next((v for v in VARIANTS if chosen and v[0]==chosen['run_id']),None)
    decision={'selected':spec[0] if spec else None,'target_r':spec[1] if spec else None,'partial_exit':spec[2] if spec else None,
              'training_passed':bool(passed),'metrics':{k:chosen.get(k) for k in ['trades','active_calendar_days','net_win_rate_pct','net_pnl','profit_factor','max_drawdown']} if chosen else None,
              'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
              'training_sha256':hashlib.sha256((HERE/'前四月训练候选.json').read_bytes()).hexdigest(),
              'note':'A selection after failed training is diagnostic only, not an accepted candidate.'}
    flow.dump(HERE/'全时段五秒冻结决定.json',decision)
    print('ALLFLOW_SELECTION',json.dumps(decision,ensure_ascii=False),flush=True)
    if not spec:return
    name,target,partial=spec;base='allflow_strong_partial_2r' if partial else 'allflow_strong_1r'
    checks=[spec] if name==base else [spec,next(v for v in VARIANTS if v[0]==base)]
    validations=[]
    for year,start,end,period in [(2024,'2024-05-01','2024-06-29','validation_may_jun_2024'),
                                  (2026,'2026-05-01','2026-07-31','research_may_jul_2026')]:
        if year!=2024:
            del market,guard;gc.collect();r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
        subset=s[s.source_year.eq(str(year))].copy()
        if year==2024:
            lo=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000);subset=subset[subset.decision_ts.ge(lo)].copy()
        for testname,tgt,part in checks:
          for lev,cost in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
            validations.append(flow.simulate(subset,testname,start,end,market,guard,lev,cost,period,target_override=tgt,partial_exit=part))
    assert hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()==decision['plan_sha256']
    assert hashlib.sha256((HERE/'前四月训练候选.json').read_bytes()).hexdigest()==decision['training_sha256']
    flow.dump(HERE/'全时段五秒后续账户.json',validations)
    print('ALLFLOW_VALIDATION_COMPLETE',len(validations),'valid',sum(v['valid_for_comparison'] for v in validations),flush=True)
if __name__=='__main__':main()
