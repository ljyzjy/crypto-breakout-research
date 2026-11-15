"""Freeze, validate and execute the three approved experiments without searching parameters."""
import hashlib,json,time
from pathlib import Path
import pandas as pd
import opt_engine as opt
from opt_engine import ROOT,RESEARCH,engine
from st_study import freeze as original_freeze,summary

def hash_file(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def freeze():
    original=original_freeze()
    paths=[ROOT/n for n in ['opt_engine.py','test_optimization.py','run_optimization.py','protocol.json']]
    paths += [RESEARCH/'profitability-diagnosis/优化方向与验证方案.txt']
    hashes={str(p.relative_to(engine.KIT)):hash_file(p) for p in paths}
    for p in engine.KIT.rglob('config.dashboard.local.json'):
        hashes[str(p.relative_to(engine.KIT))]=hash_file(p)
    payload={'original_inputs':original,'new_inputs':hashes}
    file=ROOT/'frozen.json'
    if file.exists():
        previous=engine.read(file)
        assert previous['original_inputs']==original and previous['new_inputs']==hashes,'Frozen input changed'
    else:
        engine.dump(file,{**payload,'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'before_new_outcomes':True})
    return payload

def matrix():
    windows=engine.read(RESEARCH/'protocol.json')['windows'];items=[]
    for resolution,keys,fees,delay in [('1h',list(windows),[.001,.002,.003],0),('5m',['later','2025','2026'],[.001,.002,.003],0),('5m',['later'],[.001],5)]:
        for window in keys:
            for fee in fees:
                for variant in opt.VARIANTS:items.append((window,*windows[window],variant,fee,resolution,delay))
    assert len(items)==93
    return items

def decisions(metrics):
    def get(v,w,f=.001,r='1h',d=0):
        return next(x for x in metrics if (x['mode'],x['window'],x['fee'],x['resolution'],x['delay_minutes'])==(v,w,f,r,d))
    result=[]
    for v in opt.VARIANTS:
        later=get(v,'later');detail=get(v,'later',r='5m');delay=get(v,'later',r='5m',d=5)
        gates={'later_net_positive':later['return_pct']>0,'2025_positive':get(v,'2025')['return_pct']>0,
            '2026_positive':get(v,'2026')['return_pct']>0,'later_30_trades':later['trade_count']>=30,
            'double_cost_positive':get(v,'later',.002)['return_pct']>0,'five_minute_positive':detail['return_pct']>0,
            'delayed_positive':delay['return_pct']>0,'later_no_missing_held_prices':all(x['valid_for_comparison'] for x in [later,detail,delay])}
        gates={k:bool(x) for k,x in gates.items()}
        result.append({'mode':v,'name':opt.VARIANTS[v]['name'],'gates':gates,'passes':all(gates.values()),
            'both_coins_positive':all(x>0 for x in later['contributions'].values()),
            'top3_profit_share':later['top3_profit_share']})
    return result

def check_result(r):
    data,original=engine.inputs()
    fs=opt.signal_frames(data,original,r['mode'],r['fee']);parent=r['parent_mode']
    for order in r['orders']:
        if order['side']!='buy':continue
        assert order['information_ts']==order['ts']-r['delay_minutes']*60
        info=pd.Timestamp(order['information_ts'],unit='s',tz='UTC')
        assert info.minute==0 and info.second==0
        source=info-pd.Timedelta(hours=1)
        frame=fs[order['symbol']]
        assert bool(frame.loc[source,parent+'_buy']) and not bool(frame.loc[source,parent+'_sell'])
        if r['mode']=='breakout_4h_entry':assert info.hour%4==0
        assert abs(order['qty']*order['price']-100)<1e-8
    assert r['open_positions']==0 and r['cash_min']>=0 and r['ledger_error']<1e-7
    assert abs(sum(t['pnl'] for t in r['trades'])-(r['final_equity']-1000))<1e-7
    for trade in r['trades']:
        assert abs(trade['gross_pnl']-trade['fees']-trade['slippage']-trade['pnl'])<1e-8

def run(validate_only=False):
    frozen=freeze();start=time.time()
    from test_optimization import run as validate
    validation=validate();engine.dump(ROOT/'validation.json',validation)
    print('VALIDATION PASS; registered inputs are frozen',flush=True)
    if validate_only:return
    metrics=[]
    for i,(window,begin,end,variant,fee,resolution,delay) in enumerate(matrix()):
        r=opt.cached_run(begin,end,variant,fee,resolution,delay);check_result(r)
        row=summary(r);row['window']=window;metrics.append(row)
        if (i+1)%9==0 or i==0:print(f'Completed {i+1}/93; elapsed {time.time()-start:.1f}s',flush=True)
    assert freeze()==frozen
    engine.dump(ROOT/'metrics.json',metrics)
    pd.json_normalize(metrics).drop(columns=['data_issues']).to_csv(ROOT/'metrics.csv',index=False,encoding='utf-8-sig')
    choice=decisions(metrics);engine.dump(ROOT/'decision.json',choice)
    verification={'status':'PASS','registered_runs':len(metrics),'original_and_new_hashes_unchanged':True,
        'all_entries_qualified_using_past_information':True,'all_ledgers_reconciled':True,'cash_nonnegative':True,
        'data_issue_scenarios':sum(not x['valid_for_comparison'] for x in metrics),
        'validation':validation,'elapsed_seconds':time.time()-start}
    engine.dump(ROOT/'verification.json',verification)
    selected=[r for r in metrics if r['window']=='later' and r['fee']==.001 and r['resolution']=='1h']
    print(pd.DataFrame(selected)[['mode','return_pct','max_drawdown','trade_count','mean_trade_pnl','fees','slippage_cost','contributions']].to_string(index=False))
    print('DECISIONS',json.dumps(choice,ensure_ascii=False))

if __name__=='__main__':
    import sys
    run('--validate-only' in sys.argv)
