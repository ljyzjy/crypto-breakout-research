from common import *
from datetime import datetime,timezone

def daily_stats(curve,trades):
    q=curve.copy();q['date']=pd.to_datetime(q.ts-M,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    daily=q.groupby('date').agg(equity=('equity','last'),active_minutes=('active_in_minute','sum'),halted_minutes=('permanent_paused','sum')).reset_index()
    daily['net_change']=daily.equity-daily.equity.shift(fill_value=1000.)
    if trades:
        t=pd.DataFrame(trades);t['date']=pd.to_datetime(t.exit_ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
        z=t.groupby('date').agg(trades=('net','size'),wins=('net',lambda v:int((v>0).sum())),trade_net=('net','sum')).reset_index();daily=daily.merge(z,on='date',how='left')
    else:
        for k in ['trades','wins','trade_net']:daily[k]=0
    daily[['trades','wins','trade_net']]=daily[['trades','wins','trade_net']].fillna(0)
    return daily

def bootstrap(daily):
    if daily.trades.sum()<100 or daily.active_minutes.gt(0).sum()<30:return {'available':False,'reason':'Fewer than100 trades or30 active calendar days'}
    rng=np.random.default_rng(20261113);n=len(daily);data=daily[['wins','trades','net_change']].to_numpy(float);draws=[]
    for j in range(2000):
        starts=rng.integers(0,n-6,size=int(np.ceil(n/7)));ids=np.concatenate([np.arange(s,s+7) for s in starts])[:n];sums=data[ids].sum(axis=0)
        if sums[1]>0:draws.append([100*sums[0]/sums[1],sums[2]])
    a=np.array(draws)
    return {'available':True,'method':'7-calendar-day moving blocks; zero-trade days retained; retrospective descriptive interval','win_rate_pct_95':np.quantile(a[:,0],[.025,.975]).tolist(),'net_pnl_95':np.quantile(a[:,1],[.025,.975]).tolist(),'draws':len(a)}

def run_one(variant,scenario,signals,guard):
    summary,curve,trades,entries,funding=simulate(scenario,signals,'2025-07-01','2026-04-26',market=Market(),guard=guard,save=False,run_id=variant)
    dest=OUT/'accounts'/variant;dest.mkdir(parents=True,exist_ok=True);tag=scenario['id']
    daily=daily_stats(curve,trades)
    summary['active_calendar_days']=int(daily.active_minutes.gt(0).sum());summary['fully_cash_calendar_days']=int(daily.active_minutes.eq(0).sum());summary['fully_halted_calendar_days']=int(daily.halted_minutes.eq(1440).sum())
    summary['net_win_rate_pct']=summary['win_rate'] if trades else None
    summary['net_win_count']=sum(t['net']>0 for t in trades)
    summary['funding_ledger_error']=float(sum(t['funding'] for t in trades)-sum(f['actual_charge'] for f in funding))
    summary['net_ledger_error']=float(summary['final_equity']-1000-sum(t['net'] for t in trades))
    summary['primary_numeric_targets_met']=bool(trades and summary['win_rate']>=60 and summary['net_pnl']>0 and summary['max_drawdown']<=15 and summary['intrabar_stress_dd']<=15)
    summary['sample_sufficient']=len(trades)>=100 and summary['active_calendar_days']>=30
    summary['acceptance_pass']=bool(summary['valid_for_comparison'] and summary['primary_numeric_targets_met'] and summary['sample_sufficient'] and (summary['profit_factor'] or 0)>1)
    summary['uncertainty']=bootstrap(daily)
    assert abs(summary['net_ledger_error'])<1e-8 and abs(summary['funding_ledger_error'])<1e-8
    assert all(e['feature_known_ts']<=e['decision_ts']<e['ts'] for e in entries)
    curve.to_parquet(dest/f'{tag}-curve.parquet',index=False);daily.to_csv(dest/f'{tag}-daily.csv',index=False)
    for name,obj in [('summary',summary),('trades',trades),('entries',entries),('funding',funding)]:dump(dest/f'{tag}-{name}.json',obj)
    print('ACCOUNT',variant,tag,json.dumps({k:summary[k] for k in ['trades','net_win_rate_pct','return_pct','max_drawdown','valid_for_comparison']}),flush=True)
    return summary

def main():
    frozen=read(OUT/'models/FROZEN.json');assert sha(OUT/'predictions/all.parquet')==frozen['prediction_sha256']
    for f,expected in frozen['models'].items():assert sha(OUT/'models'/f)==expected
    pred=pd.read_parquet(OUT/'predictions/all.parquet');guard=RankTrendGuard()
    dump(OUT/'account_execution_freeze.json',{'utc':datetime.now(timezone.utc).isoformat(),'models_frozen_sha256':sha(OUT/'models/FROZEN.json'),'engine_sha256':sha(P3/'account/engine.py'),'runner_sha256':sha(Path(__file__)),'protocol_sha256':sha(OUT/'protocol.json'),'thresholds_changed_after_calibration':False})
    baseline=pd.read_parquet(P3/'account/event-signals.parquet')
    a=run_one('A',PROTOCOL['cost_scenarios'][0],baseline,guard)
    prior=read(P3/'account/results/event_baseline/main-summary.json')
    for k in ['trades','return_pct','max_drawdown','gross_pnl','fees','slippage_cost','funding_cost','net_pnl','profit_factor']:
        assert np.isclose(a[k],prior[k],rtol=0,atol=1e-10),(k,a[k],prior[k])
    results=[a]
    for variant in ['B','C']:
        signals=pred[pred.variant.eq(variant)&pred.split.eq('evaluation')&pred.filter_pass].copy()
        for scenario in PROTOCOL['cost_scenarios']:results.append(run_one(variant,scenario,signals,guard))
    dump(OUT/'account_results.json',{'results':results,'A_exact_reproduction':True,'B_C_model_thresholds_frozen':True,'leverage_cap':1,'paper_changed':False,'historical_not_pristine_holdout':True})
    print('ACCOUNTS_READY',flush=True)

if __name__=='__main__':main()
