"""Frozen comparison of first- and later-minute breakout candidates."""
import gc,hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):
    sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
flow.HERE=HERE;flow.eng=flow.load('expanded_partial_engine',PARENT/'第十二轮_分批保护'/'partial_engine.py')
VARIANTS=[('wide_hold_1r',1.,False),('wide_preflow_1r',1.,False),('wide_preflow_follow_1r',1.,False),
          ('wide_hold_partial_2r',2.,True),('wide_preflow_partial_2r',2.,True),('wide_preflow_follow_partial_2r',2.,True)]
def select(s,name):
    mask=(s.side*(s.raw_entry_5s-s.level)>0)
    if '_preflow_' in name:mask &= s.previous_signed_flow.ge(.1)
    if '_follow_' in name:mask &= s.side*(s.raw_entry_5s-s.signal_close)>0
    return s[mask].copy()
flow.candidate=select
def load_data():
    first=PARENT/'第十四轮_首分钟逐笔突破';later=PARENT/'第六轮_柱内首次触价'
    meta1=json.loads((first/'首分钟逐笔校验档案.json').read_text(encoding='utf-8'))
    meta2=json.loads((later/'逐笔触价档案校验_训练.json').read_text(encoding='utf-8'))
    fatal={'archive_error','no_trigger_data','ohlc_trade_mismatch','no_price_reference','no_price_before_candle_end','minute_archive_mismatch'}
    if meta1['archive_errors'] or meta2['archive_errors'] or any(meta1['statuses'].get(x,0) or meta2['statuses'].get(x,0) for x in fatal):
        raise ValueError('incomplete_verified_tapes')
    x=pd.read_parquet(first/'首分钟首次触价与五秒参考.parquet');y=pd.read_parquet(later/'逐笔首次触价与五秒入场_训练.parquet')
    x=x[x.status.eq('verified')].copy();x['cohort']='opening'
    y=y[y.status.eq('verified')].copy();y['cohort']='later'
    s=pd.concat([x,y],ignore_index=True);assert s.observation_id.is_unique
    assert not s.duplicated(['symbol','quarter_start']).any()
    assert (s.entry_exec_ts>=s.decision_ts+5000).all() and (s.entry_exec_ts<s.quarter_end).all()
    s['tick_status']='verified';groups=[]
    for (year,contract),g in s.groupby(['source_year','contract']):
        folder='breakout_november_2026' if year=='2026' else 'breakout_2024_11'
        raw=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{contract}_klines.parquet',
                            columns=['ts','quote_volume','taker_buy_quote_volume']).set_index('ts')
        assert raw.index.is_unique
        prev=raw.reindex(g.trigger_minute.to_numpy('int64')-60_000)
        total=prev.quote_volume.to_numpy(float);buy=prev.taker_buy_quote_volume.to_numpy(float)
        valid=np.isfinite(total)&np.isfinite(buy)&(total>0)&(buy>=0)&(buy<=total*(1+1e-8))
        imb=np.full(len(g),np.nan);imb[valid]=g.side.to_numpy()[valid]*(2*buy[valid]/total[valid]-1)
        out=g.copy();out['previous_signed_flow']=imb;out['previous_flow_known_ts']=out.trigger_minute
        groups.append(out)
    s=pd.concat(groups,ignore_index=True).sort_values(['decision_ts','symbol']).reset_index(drop=True)
    s.to_parquet(HERE/'合并候选与事前主动成交.parquet',index=False)
    meta={'events':len(s),'cohort_counts':s.cohort.value_counts().to_dict(),
          'year_counts':s.source_year.value_counts().to_dict(),'missing_previous_flow':int(s.previous_signed_flow.isna().sum())}
    flow.dump(HERE/'合并候选质量.json',meta);print('EXPANDED_EVENTS',json.dumps(meta,ensure_ascii=False),flush=True)
    return s
def main():
    s=load_data();r2.configure(2024);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    train=s[s.source_year.eq('2024')].copy();results=[]
    for name,target,partial in VARIANTS:
        results.append(flow.simulate(train,name,'2024-01-01','2024-04-30',market,guard,20,'main','train_jan_apr_2024',
                    target_override=target,partial_exit=partial))
    flow.dump(HERE/'前四月训练全部候选.json',results)
    viable=[v for v in results if v['valid_for_comparison'] and v['trades']>=30]
    passed=[v for v in viable if v['net_win_rate_pct'] is not None and v['net_win_rate_pct']>=60 and v['net_pnl']>0
            and v['profit_factor'] is not None and v['profit_factor']>1]
    chosen=max(passed or viable,key=lambda v:v['net_pnl']) if viable else None
    spec=next((v for v in VARIANTS if chosen and v[0]==chosen['run_id']),None)
    decision={'selected':spec[0] if spec else None,'target_r':spec[1] if spec else None,'partial_exit':spec[2] if spec else None,
              'training_passed':bool(passed),'metrics':{k:chosen.get(k) for k in ['trades','active_calendar_days','net_win_rate_pct','net_pnl','profit_factor','max_drawdown']} if chosen else None,
              'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
              'training_sha256':hashlib.sha256((HERE/'前四月训练全部候选.json').read_bytes()).hexdigest(),
              'note':'If training failed, the selected candidate is a diagnostic, not an accepted strategy.'}
    flow.dump(HERE/'扩展时段冻结决定.json',decision)
    print('EXPANDED_SELECTION',json.dumps(decision,ensure_ascii=False),flush=True)
    if not spec:return
    name,target,partial=spec
    base='wide_hold_partial_2r' if partial else 'wide_hold_1r'
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
    assert hashlib.sha256((HERE/'前四月训练全部候选.json').read_bytes()).hexdigest()==decision['training_sha256']
    flow.dump(HERE/'扩展时段后续账户.json',validations)
    print('EXPANDED_VALIDATION_COMPLETE',len(validations),'valid',sum(v['valid_for_comparison'] for v in validations),flush=True)
if __name__=='__main__':main()
