"""Add funding and conservative mark-risk checks, then freeze unit-path selection."""
import gc,hashlib,importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;M=60_000
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
sp=importlib.util.spec_from_file_location('unit29_eval_config',PARENT/'第二十八轮_原十八币池扩展'/'generate_18_candidates.py')
config=importlib.util.module_from_spec(sp);sys.modules[sp.name]=config;sp.loader.exec_module(config)
def risk_and_funding(row,market):
    side=int(row.side);entry_ts=int(row.entry_ts);exit_ts=int(row.exit_ts);entry=float(row.entry_fill);qty=1./entry
    funding=0.;marks=[];events=[]
    for ts in range(entry_ts//M*M,exit_ts//M*M+M,M):
        mark=market.bar(row.contract,ts,True)
        if mark is None:return {'risk_status':'missing_mark','funding':None,'liq_proxy':None,'funding_events':[]}
        if not market.funding_ok(row.contract,ts):return {'risk_status':'missing_funding_coverage','funding':None,'liq_proxy':None,'funding_events':[]}
        marks.append(float(mark[2] if side==1 else mark[1]))
        for ft,rate in market.funding.get(row.contract,{}).get(ts,[]):
            if not entry_ts<=ft<=exit_ts:continue
            signed=side*qty*float(mark[0])*float(rate)
            charge=max(0.,signed) if ft in (entry_ts,exit_ts) else signed
            funding+=charge;events.append({'settlement_ts':int(ft),'rate':float(rate),'mark_open':float(mark[0]),
                                           'signed_charge':signed,'actual_charge':charge})
    liq=any((1/20-.0005-max(funding,0.)+side*qty*(x-entry))<=qty*x*(.005+.005) for x in marks)
    exit_fill=float(row.exit_fill);exit_fee=qty*exit_fill*.0005
    net=side*qty*(exit_fill-entry)-.0005-exit_fee-funding
    return {'risk_status':'verified','funding':funding,'liq_proxy':bool(liq),'funding_events':events,
            'entry_fee':.0005,'exit_fee':exit_fee,'net_per_unit_notional':net,'net_pct_notional':100*net}
def metrics(frame):
    values=frame.net_per_unit_notional.to_numpy(float);wins=values>0;loss=values<0
    pos=float(values[wins].sum());neg=float(-values[loss].sum())
    return {'events':len(values),'net_wins':int(wins.sum()),'net_win_rate_pct':float(100*wins.mean()) if len(values) else None,
            'sum_net_per_unit_notional':float(values.sum()),'average_net_pct_notional':float(100*values.mean()) if len(values) else None,
            'profit_factor':pos/neg if neg else None,'liq_proxy_events':int(frame.liq_proxy.fillna(False).sum()),
            'filled_beyond_risk_budget':int(frame.reason.eq('filled_beyond_risk_budget').sum())}
def main():
    meta=json.loads((HERE/'秒级路径档案与排除记录.json').read_text(encoding='utf-8'))
    selected=pd.read_parquet(HERE/'事前条件通过候选.parquet')
    paths=pd.read_parquet(HERE/'秒级路径与延迟参考.parquet')
    d=paths.merge(selected[['observation_id','symbol','contract','side','source_year','decision_ts','quarter_end','cohort']],
                  on='observation_id',validate='many_to_one')
    assert len(d)==4*len(selected) and not d.duplicated(['observation_id','variant']).any()
    bad=d[~d.status.eq('verified')]
    if len(bad) or meta['archive_errors']:
        flow.dump(HERE/'秒级筛查完整性.json',{'complete':False,'path_statuses':d.status.value_counts().to_dict(),
                  'archive_errors':meta['archive_errors'],'note':'No problematic path was removed to claim success.'})
        print('SECONDS29_INCOMPLETE',len(bad),flush=True);return
    pieces=[]
    for year in (2024,2026):
        r2.configure(year)
        if year==2026:
            # July 31 late events can settle on Aug 1; include the next day of verified market data.
            f=flow.forward;f.END=int(pd.Timestamp('2026-08-02',tz='UTC').timestamp()*1000)
            f.GRID=np.arange(f.WARM,f.END,M,dtype=np.int64)
        market=flow.forward.FixedMarket();subset=d[d.source_year.eq(str(year))].copy()
        checked=[risk_and_funding(r,market) for r in subset.itertuples(index=False)]
        z=pd.concat([subset.reset_index(drop=True),pd.DataFrame(checked)],axis=1);pieces.append(z)
        del market,subset,z;gc.collect()
    allpaths=pd.concat(pieces,ignore_index=True);allpaths.to_parquet(HERE/'秒级净收益与风险核算.parquet',index=False)
    missing=allpaths[~allpaths.risk_status.eq('verified')];liq=int(allpaths.liq_proxy.fillna(False).sum())
    complete=bool(not len(missing) and liq==0)
    quality={'complete':complete,'paths':len(allpaths),'missing_risk_paths':len(missing),'liq_proxy_paths':liq,
             'status_counts':allpaths.risk_status.value_counts().to_dict(),
             'note':'Any missing risk coverage or proxy liquidation prevents the screen from passing.'}
    flow.dump(HERE/'秒级筛查完整性.json',quality)
    if not complete:
        print('SECONDS29_RISK_INCOMPLETE',json.dumps(quality,ensure_ascii=False),flush=True);return
    train_end=int(pd.Timestamp('2024-05-01',tz='UTC').timestamp()*1000)
    val_lo=int(pd.Timestamp('2024-05-01 01:00',tz='UTC').timestamp()*1000)
    val_hi=int(pd.Timestamp('2024-06-30',tz='UTC').timestamp()*1000)
    # The outcome of every training event must be knowable before the cutoff.
    # Use the candle clock known when the signal is generated (not the observed
    # exit), and allow the full extra minute reserved for the delayed fill.
    # This applies the identical pre-outcome embargo to all four variants.
    train=allpaths[allpaths.source_year.eq('2024')&((allpaths.quarter_end+M).le(train_end))]
    assert train.exit_ts.lt(train_end).all(), 'training outcome crossed the cutoff'
    variants=['normal_1r','fast_1r','normal_2r','fast_2r']
    train_scores=[{'variant':n,**metrics(train[train.variant.eq(n)])} for n in variants]
    flow.dump(HERE/'秒级训练机会对照.json',train_scores)
    viable=[x for x in train_scores if x['events']>=50]
    passed=[x for x in viable if x['net_win_rate_pct']>=60 and x['sum_net_per_unit_notional']>0 and
            x['profit_factor'] is not None and x['profit_factor']>1]
    chosen=max(passed or viable,key=lambda x:x['average_net_pct_notional']) if viable else None
    decision={'selected':chosen['variant'] if chosen else None,'training_screen_passed':bool(passed),'training_metrics':chosen,
              'complete':complete,'plan_sha256':hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest(),
              'train_sha256':hashlib.sha256((HERE/'秒级训练机会对照.json').read_bytes()).hexdigest(),
              'source_sha256':hashlib.sha256((HERE/'秒级净收益与风险核算.parquet').read_bytes()).hexdigest(),
              'training_clock_embargo':'Only events with quarter_end + 60 seconds <= 2024-05-01 00:00 UTC are used; applied before outcomes equally to all four variants.',
              'note':'Unit-notional opportunity paths; not a shared-account trading result.'}
    flow.dump(HERE/'秒级冻结筛选决定.json',decision)
    print('SECONDS29_TRAIN_SELECTION',json.dumps(decision,ensure_ascii=False),flush=True)
    if not chosen:return
    target=chosen['variant'].split('_')[-1];variants_check=[f'normal_{target}',f'fast_{target}']
    output=[]
    for period,subset in [('validation_may_jun_2024',allpaths[allpaths.source_year.eq('2024')&allpaths.decision_ts.ge(val_lo)&allpaths.decision_ts.lt(val_hi)]),
                          ('research_may_jul_2026',allpaths[allpaths.source_year.eq('2026')])]:
        for name in variants_check:output.append({'period':period,'variant':name,**metrics(subset[subset.variant.eq(name)])})
    assert hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()==decision['plan_sha256']
    assert hashlib.sha256((HERE/'秒级训练机会对照.json').read_bytes()).hexdigest()==decision['train_sha256']
    flow.dump(HERE/'秒级后续机会对照.json',output)
    pd.DataFrame(train_scores+output).to_csv(HERE/'秒级逐机会对照.csv',index=False,encoding='utf-8-sig')
    print('SECONDS29_COMPARISON_COMPLETE',json.dumps(output,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
