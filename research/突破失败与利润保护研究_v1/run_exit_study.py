"""Fixed-rules account experiments on old history and optional later dates."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
GE=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge')
P3=GE/'outputs'/'feature-research-phase3'/'account'
PREV=HERE.parent/'突破胜率与净收益前瞻检验_v1'
ORIGINAL=HERE.parent/'突破柱融合研究_v1'
NOV=ROOT/'work'/'breakout_november_2026'
CURVES=NOV/'study_curves';CURVES.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(P3))
from account_market import Market,RankTrendGuard
def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp)
    sys.modules[name]=m;sp.loader.exec_module(m);return m
forward=load('exit_forward',PREV/'forward_research.py')
eng=load('exit_rules_engine',HERE/'exit_engine.py')
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,
       default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')

def run_set(period,start,end,signals,market,guard):
    variants=[('base_2r',False,False),('failure_exit',True,False),('lock_profit',False,True),('combined',True,True)]
    costs=[('main',.0005,.0005,0),('double',.001,.001,0),('delay1',.0005,.0005,1)]
    out=[]
    for name,fail,lock in variants:
      for tag,fee,slip,delay in costs:
        sc={'id':tag,'fee':fee,'slippage':slip,'delay_minutes':delay,'target_r':2.,'failure_exit':fail,'lock_profit':lock}
        sm,curve,trades,entries,funding=eng.simulate(sc,signals,start,end,market=market,guard=guard,save=False,run_id=name)
        sm['period']=period;sm['net_win_rate_pct']=sm['win_rate'] if trades else None
        sm['failure_scheduled_count']=sum(e['kind']=='failure_scheduled' for e in sm['rule_events'])
        sm['lock_scheduled_count']=sum(e['kind']=='lock_scheduled' for e in sm['rule_events'])
        sm['lock_applied_count']=sum(e['kind']=='lock_applied' for e in sm['rule_events'])
        sm['failure_exit_count']=sum(t['reason']=='failed_breakout' for t in trades)
        sm['winning_trade_count']=sum(t['net']>0 for t in trades)
        if len(curve):
            days=(curve.ts.to_numpy()-1)//86_400_000
            sm['active_calendar_days']=int(pd.DataFrame({'day':days,'active':curve.active_in_minute}).groupby('day').active.any().sum())
        else:sm['active_calendar_days']=0
        if sm['valid_for_comparison']:
            assert abs(sm['final_equity']-1000-sum(t['net'] for t in trades))<1e-6
            assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in funding))<1e-6
        for t in trades:
            side=1 if t['side']=='long' else -1
            assert np.isclose(t['entry'],t['raw_entry']*(1+side*slip),rtol=1e-10,atol=1e-10)
            assert np.isclose(t['exit'],t['raw_exit']*(1-side*slip),rtol=1e-10,atol=1e-10)
            if t['lock_applied_ts']:
                assert t['lock_applied_ts']>=t['lock_known_ts']+60_000
            if t['reason']=='failed_breakout':
                assert t['failure_known_ts'] and t['exit_ts']>=t['failure_known_ts']+60_000
        for e in sm['rule_events']:
            assert e['effective_ts']>=e['known_ts']+60_000
        sm['acceptance_pass']=bool(sm['valid_for_comparison'] and sm['net_win_rate_pct'] is not None and
            sm['net_win_rate_pct']>=60 and sm['net_pnl']>0 and sm['profit_factor'] is not None and sm['profit_factor']>1 and
            sm['max_drawdown']<=15 and len(trades)>=100 and sm['active_calendar_days']>=30)
        if name=='base_2r' and tag=='main' and period in ('old_dynamic','fixed_full'):
            src=(ORIGINAL/'early_sync_main_summary.json') if period=='old_dynamic' else (PREV/'full_baseline_2r_main_summary.json')
            old=json.loads(src.read_text(encoding='utf-8'))
            assert sm['trades']==old['trades'] and abs(sm['net_pnl']-old['net_pnl'])<1e-8
        stem=f'{period}_{name}_{tag}'
        dump(HERE/f'{stem}_summary.json',sm);dump(HERE/f'{stem}_trades.json',trades)
        dump(HERE/f'{stem}_entries.json',entries);dump(HERE/f'{stem}_funding.json',funding)
        curve.to_parquet(CURVES/f'{stem}.parquet',index=False)
        out.append(sm)
        print('RESULT',stem,json.dumps({k:sm.get(k) for k in ['signal_candidates','trades','net_win_rate_pct','net_pnl','max_drawdown','failure_exit_count','lock_applied_count','valid_for_comparison','issues']}),flush=True)
    return out

def main():
    report=json.loads((HERE/'新期间数据与校验.json').read_text(encoding='utf-8'))
    novel_complete=(report['archive_verified']==report['archive_expected'] and
                    report['funding_verified']==report['funding_expected'] and not report['noncomplete_minutes'])
    forward.NORM=NOV/'normalized';forward.HERE=HERE
    forward.START=int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000)
    forward.END=int(pd.Timestamp('2026-11-13',tz='UTC').timestamp()*1000)
    forward.GRID=np.arange(forward.WARM,forward.END,forward.M,dtype=np.int64)
    market=forward.FixedMarket();guard=forward.FixedGuard(market)
    forward.validate_warm_features(guard)
    nov_first,_=forward.create_signals(market,guard)
    fixed=pd.read_parquet(PREV/'first_signals.parquet')
    old=pd.read_parquet(ORIGINAL/'signals.parquet');old=old[old.sync_pass].copy()
    results=[]
    results+=run_set('fixed_full','2026-05-01','2026-10-31',fixed,market,guard)
    results+=run_set('fixed_may_jul','2026-05-01','2026-07-31',fixed,market,guard)
    results+=run_set('fixed_aug_oct','2026-08-01','2026-10-31',fixed,market,guard)
    if novel_complete:
        results+=run_set('nov_new_12days','2026-11-01','2026-11-12',nov_first,market,guard)
    else:
        print('NOV_NOT_RUN: coverage or funding incomplete',flush=True)
    results+=run_set('old_dynamic','2025-07-01','2026-04-26',old,Market(),RankTrendGuard())
    dump(HERE/'全部策略账户结果.json',results)
    cols=['period','run_id','scenario','signal_candidates','trades','winning_trade_count','net_win_rate_pct',
          'net_pnl','return_pct','max_drawdown','intrabar_stress_dd','profit_factor','active_calendar_days',
          'failure_scheduled_count','failure_exit_count','lock_scheduled_count','lock_applied_count',
          'valid_for_comparison','acceptance_pass','issues']
    pd.DataFrame(results).reindex(columns=cols).to_csv(HERE/'完整策略回放对照.csv',index=False,encoding='utf-8-sig')
    print('EXIT_RESEARCH_COMPLETE accounts',len(results),flush=True)

if __name__=='__main__':main()
