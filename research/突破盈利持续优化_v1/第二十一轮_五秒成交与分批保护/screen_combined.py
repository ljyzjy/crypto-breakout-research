"""Fixed 2026 feasibility screening for five-second flow plus partial exits."""
import hashlib,json,sys
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交',PARENT/'第六轮_柱内首次触价'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
import train_touch as touch
flow.HERE=HERE;flow.eng=flow.load('combined_partial_engine',PARENT/'第十二轮_分批保护'/'partial_engine.py')
VARIANTS=[('combined_partial_2r',2.,True),('combined_control_2r',2.,False),
          ('combined_partial_3r',3.,True),('combined_control_3r',3.,False)]
def select(s,name):
    hold=s.side*(s.raw_entry_5s-s.level)>0
    return s[hold&s.flow5_status.eq('verified')&s.flow5_count.ge(3)&s.flow5_imbalance.ge(.1)].copy()
flow.candidate=select
def main():
    tape=PARENT/'第十九轮_突破后五秒主动成交'
    meta=json.loads((tape/'五秒主动成交档案校验.json').read_text(encoding='utf-8'))
    if meta['archive_errors']:raise ValueError('five_second_flow_archive_incomplete')
    sig=pd.read_parquet(PARENT/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
    sig=sig[sig.status.eq('verified')&sig.source_year.eq('2026')].copy();sig['tick_status']='verified'
    ft=pd.read_parquet(tape/'五秒主动成交特征_2026.parquet').rename(columns={'status':'flow5_status',
        'count':'flow5_count','directional_imbalance':'flow5_imbalance','archive_sha256':'flow_archive_sha256'})
    s=sig.merge(ft,on='observation_id',validate='one_to_one');assert len(s)==len(sig)
    good=s[s.flow5_status.eq('verified')]
    assert (good.last_ts<good.window_end).all() and (good.window_end<=good.entry_exec_ts).all()
    r2.configure(2026);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    results=[];main=[]
    for name,target,enabled in VARIANTS:
        for lev,scenario in [(20,'main'),(10,'main'),(20,'stress'),(10,'stress')]:
            sm=flow.simulate(s,name,'2026-05-01','2026-07-31',market,guard,lev,scenario,'screen_2026',target_override=target,partial_exit=enabled)
            results.append(sm)
            if lev==20 and scenario=='main':main.append(sm)
    passed=[x for x in main if x['valid_for_comparison'] and x['trades']>=30 and x['net_win_rate_pct'] is not None
            and x['net_win_rate_pct']>=60 and x['net_pnl']>0 and x['profit_factor'] is not None and x['profit_factor']>1]
    viable=[x for x in main if x['valid_for_comparison'] and x['trades']>=30]
    chosen=max(passed,key=lambda x:x['net_pnl']) if passed else None
    diagnostic=max(viable,key=lambda x:x['net_pnl']) if viable else None
    flow.dump(HERE/'组合分批保护所有账户.json',results)
    decision={'screen_passed':bool(chosen),'selected':chosen['run_id'] if chosen else None,
              'diagnostic':diagnostic['run_id'] if diagnostic else None,
              'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
              'feature_sha256':hashlib.sha256((tape/'五秒主动成交特征_2026.parquet').read_bytes()).hexdigest(),
              'note':'2026 research screen only; no claim of out-of-sample validation or sufficient trading days.'}
    flow.dump(HERE/'组合分批保护筛选结果.json',decision)
    print('COMBINED_SCREEN_COMPLETE',json.dumps(decision,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
