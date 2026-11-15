"""Execute the frozen no-selected-feature account comparison, all five costs."""
from pathlib import Path
from datetime import datetime, timezone
import json
import pandas as pd
from engine import simulate
from account_market import RankTrendGuard, Market
from market_io import sha256

ROOT=Path(__file__).resolve().parent
PARENT=ROOT.parent
EXPECTED_PROTOCOL='2eddf317fe60e07894a2e53b77738e1ab7ee03273998b6a786a333eddcb48013'


def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main():
    assert sha256(PARENT/'protocol.json')==EXPECTED_PROTOCOL
    protocol=json.loads((PARENT/'protocol.json').read_text(encoding='utf-8'))
    inc=PARENT/'incremental'
    ready=json.loads((inc/'RESULTS_READY.json').read_text(encoding='utf-8'))
    assert ready['selection_sha256']==sha256(inc/'selection.json')
    selection=json.loads((inc/'selection.json').read_text(encoding='utf-8'))
    assert selection['selected_groups']==[], 'This runner is frozen specifically for the observed none-pass branch'
    signals=pd.read_parquet(ROOT/'event-signals.parquet')
    assert signals.observation_id.is_unique
    assert signals.feature_known_ts.le(signals.decision_ts).all()
    assert signals.ts.eq(signals.decision_ts+60_000).all()
    # No selected model input restrictions: aligned and unrestricted are exact aliases.
    identity_hash=__import__('hashlib').sha256('\n'.join(sorted(signals.observation_id)).encode()).hexdigest()
    freeze={'created_utc':datetime.now(timezone.utc).isoformat(),'account_outcomes_seen':False,
        'protocol_sha256':EXPECTED_PROTOCOL,'incremental_ready_sha256':sha256(inc/'RESULTS_READY.json'),
        'selected_groups':[],'branch':'frozen_none_pass','files':{f:sha256(ROOT/f) for f in
            ['engine.py','account_market.py','market_io.py','build_signals.py','run_accounts.py',
             'accounting_amendment.json','market_manifest.json','event-signals.parquet',
             'hourly-ranks.parquet','regimes.parquet']},
        'opportunity_ids_sha256':identity_hash,'opportunities':len(signals)}
    dump(ROOT/'execution_freeze.json',freeze)
    start='2025-07-01';end='2026-04-26'
    guard=RankTrendGuard();results=[];daily=[];coins=[]
    for scenario in protocol['cost_scenarios']:
        summary,curve,trades,entries,funding=simulate(scenario,signals,start,end,market=Market(),guard=guard,run_id='event_baseline')
        curve['date']=pd.to_datetime(curve.ts-60_000,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
        days=curve.groupby('date').agg(first_equity=('equity','first'),last_equity=('equity','last'),
            active_minutes=('active_in_minute','sum'),halted_minutes=('permanent_paused','sum'),
            daily_paused_minutes=('daily_paused','sum'),minutes=('ts','size')).reset_index()
        days['scenario']=scenario['id'];days['start_equity']=days.last_equity.shift(fill_value=1000.)
        days['return_pct']=100*(days.last_equity/days.start_equity-1)
        daily.append(days)
        summary['active_calendar_days']=int(days.active_minutes.gt(0).sum())
        summary['fully_cash_calendar_days']=int(days.active_minutes.eq(0).sum())
        summary['fully_halted_calendar_days']=int(days.halted_minutes.eq(1440).sum())
        summary['calendar_days_with_any_halt']=int(days.halted_minutes.gt(0).sum())
        summary['active_days_equivalent']=summary['active_minutes']/1440
        summary['funding_events']=len(funding)
        summary['funding_ledger_error']=float(sum(t['funding'] for t in trades)-sum(f['actual_charge'] for f in funding))
        summary['causal_entry_pass']=bool(all(e['feature_known_ts']<=e['decision_ts']<e['ts'] for e in entries))
        summary['candidate_success_screen']=bool(summary['valid_for_comparison'] and summary['return_pct']>0 and
             summary['max_drawdown']<=15 and summary['intrabar_stress_dd']<=15 and
             (scenario['id']!='main' or (summary['trades']>=100 and summary['profit_factor'] is not None and summary['profit_factor']>1)))
        dump(ROOT/'results/event_baseline'/f"{scenario['id']}-summary.json",summary)
        results.append(summary)
        if trades:
            t=pd.DataFrame(trades)
            c=t.groupby(['symbol','side']).agg(trades=('net','size'),gross=('gross','sum'),fees=('fees','sum'),slippage=('slippage','sum'),funding=('funding','sum'),net=('net','sum')).reset_index()
            c['scenario']=scenario['id'];coins.append(c)
        print(json.dumps({'scenario':scenario['id'],'net_pct':summary.get('return_pct'),
            'dd_pct':summary.get('max_drawdown'),'stress_dd_pct':summary.get('intrabar_stress_dd'),
            'trades':summary.get('trades'),'valid':summary['valid_for_comparison'],'issues':summary['issues']}),flush=True)
    pd.concat(daily,ignore_index=True).to_csv(ROOT/'daily_accounts.csv',index=False)
    if coins:pd.concat(coins,ignore_index=True).to_csv(ROOT/'coin_attribution.csv',index=False)
    report={'protocol_sha256':EXPECTED_PROTOCOL,'evaluation_days':300,'selected_groups':[],
        'enhanced_candidates_run':0,'reason_no_enhanced_candidate':'All six primary tests failed the preregistered Holm threshold; F3 unadjusted significance is insufficient.',
        'baseline_comparison':{'event_baseline':'unrestricted common matured-event baseline',
            'aligned_baseline':'exact alias of event_baseline because no model selected; same opportunities, costs and results',
            'aligned_same_ids':True,'opportunity_ids_sha256':identity_hash},
        'all_five_pass_success_screen':all(r['candidate_success_screen'] for r in results),
        'cagr_reported':False,'paper_changed':False,'results':results}
    dump(ROOT/'account_results.json',report)
    dump(ROOT/'ACCOUNT_RESULTS_READY.json',{'summary_sha256':sha256(ROOT/'account_results.json'),
        'execution_freeze_sha256':sha256(ROOT/'execution_freeze.json'),'scenarios':len(results)})
    print('ALL_ACCOUNT_SCENARIOS_COMPLETE',flush=True)


if __name__=='__main__':main()
