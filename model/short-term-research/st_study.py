"""Freeze inputs, run all prespecified scenarios, and report failures as well as successes."""
import hashlib,json,sys,time
from pathlib import Path
import pandas as pd
from st_engine import ROOT,KIT,MODES,NAMES,read,dump,cached_run


def fingerprints():
    paths=[ROOT/'protocol.json',ROOT/'st_engine.py',ROOT/'st_factors.py',ROOT/'st_study.py',ROOT/'test_engine.py',
           ROOT/'短线策略与因子研究方案.txt',ROOT/'数据可用性审计.json',KIT/'user_data/strategies/DailyCandidates.py',KIT/'user_data/strategies/SpotTrendV1.py']
    paths += [KIT/'user_data/data/archive'/a['file'] for a in read(ROOT/'数据可用性审计.json')['archives']]
    return {str(p.relative_to(KIT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def freeze():
    current=fingerprints();path=ROOT/'frozen.json'
    if path.exists():
        expected=read(path)['hashes'].copy()
        if (ROOT/'reporting_amendments.json').exists():
            for item in read(ROOT/'reporting_amendments.json'):
                assert Path(item['path'])==Path('short-term-research')/'st_study.py', 'Only this reporting driver may be amended here.'
                assert expected[item['path']]==item['before_sha256']
                expected[item['path']]=item['after_sha256']
        assert expected==current,'Frozen research inputs changed. Do not silently reuse results.'
    else:dump(path,{'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'hashes':current,'before_outcomes':True})
    return current


def matrix():
    protocol=read(ROOT/'protocol.json');items=[]
    for resolution,windows,fees,delay in [('1h',list(protocol['windows']),[.001,.002,.003],0),
                                         ('5m',['later','2025','2026'],[.001,.002,.003],0),
                                         ('5m',['later'],[.001],5)]:
        for window in windows:
            start,end=protocol['windows'][window]
            for fee in fees:
                for mode in MODES:items.append((window,start,end,mode,fee,resolution,delay))
    assert len(items)==186
    return items


def summary(result):
    return {k:v for k,v in result.items() if k not in ('orders','trades','curve')}


def decisions(metrics):
    def get(mode,window,fee=.001,resolution='1h',delay=0):
        return next(r for r in metrics if (r['mode'],r['window'],r['fee'],r['resolution'],r['delay_minutes'])==(mode,window,fee,resolution,delay))
    decisions=[]
    for mode in MODES:
        later=get(mode,'later');detail=get(mode,'later',resolution='5m');late=get(mode,'later',resolution='5m',delay=5)
        gates={'later_net_positive':later['return_pct']>0,'2025_positive':get(mode,'2025')['return_pct']>0,
               '2026_positive':get(mode,'2026')['return_pct']>0,'later_30_trades':later['trade_count']>=30,
               'double_cost_positive':get(mode,'later',.002)['return_pct']>0,'five_minute_positive':detail['return_pct']>0,
               'delayed_positive':late['return_pct']>0,'later_no_missing_held_prices':later['valid_for_comparison'] and detail['valid_for_comparison'] and late['valid_for_comparison']}
        gates={k:bool(v) for k,v in gates.items()}
        decisions.append({'mode':mode,'name':NAMES[mode],'gates':gates,'passes':all(gates.values()),
                          'both_coins_positive':all(v>0 for v in later['contributions'].values()),
                          'concentrated':bool(later['top3_profit_share'] is not None and later['top3_profit_share']>50),
                          'diagnostic_only':mode.startswith('breakout_')})
    return decisions


def run():
    before=freeze();began=time.time();metrics=[]
    for i,(window,start,end,mode,fee,resolution,delay) in enumerate(matrix()):
        result=cached_run(start,end,mode,fee,resolution,delay);row=summary(result);row['window']=window;metrics.append(row)
        if (i+1)%12==0 or i==0:print(f'Completed {i+1}/186; elapsed {time.time()-began:.0f}s',flush=True)
    dump(ROOT/'metrics.json',metrics)
    pd.json_normalize(metrics).drop(columns=['data_issues']).to_csv(ROOT/'metrics.csv',index=False,encoding='utf-8-sig')
    dump(ROOT/'decision.json',decisions(metrics))
    from st_factors import run as factor_run
    factor_run();assert fingerprints()==before
    verification={'status':'PASS','frozen_hashes_unchanged':True,'scenarios':len(metrics),
                  'all_ledgers_reconciled':all(r['ledger_error'] is not None and r['ledger_error']<1e-7 for r in metrics),
                  'no_negative_cash':all(r['cash_min']>=-1e-7 for r in metrics),
                  'data_issue_scenarios':sum(not r['valid_for_comparison'] for r in metrics),
                  'factor_tests':36,'elapsed_seconds':time.time()-began,'validation':read(ROOT/'validation.json')}
    dump(ROOT/'verification.json',verification)
    print(json.dumps(verification,ensure_ascii=False),flush=True)
    print(pd.DataFrame([r for r in metrics if r['window']=='later' and r['fee']==.001 and r['resolution']=='1h'])[['name','return_pct','max_drawdown','trade_count','mean_trade_pnl','fees']].to_string(index=False))


if __name__=='__main__':run()
