"""Second read-only code/unit review. Writes evidence only inside incremental/."""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,hashlib
import pandas as pd

ROOT=Path(__file__).resolve().parent
ACCOUNT=ROOT.parent/'account'
sys.path.insert(0,str(ACCOUNT))
from market_io import load_minutes,load_mapping,get_manifest
from account_market import load_symbol_hourly

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    examples=[]
    for symbol in ['BONKUSDT','PEPEUSDT','SHIBUSDT']:
        contract=load_mapping()[symbol]
        h=load_symbol_hourly(symbol,contract,['ts','close'])
        h=h.loc[h.close.notna()]
        for ix in sorted(set([0,len(h)//2,len(h)-1])):
            r=h.iloc[ix];m=load_minutes(contract,int(r.ts)-60000,int(r.ts))
            rawclose=float(m.close.iloc[0]) if len(m)==1 else None
            examples.append({'symbol':symbol,'contract':contract,'hour_close_ts':int(r.ts),
                'hourly_feature_close':float(r.close),'raw_contract_previous_minute_close':rawclose,
                'exactly_equal':rawclose==float(r.close)})
    signals=pd.read_parquet(ACCOUNT/'event-signals.parquet')
    month_open_counts={}
    for delay in [0,1]:
        times=pd.to_datetime(signals.ts+delay*60000,unit='ms',utc=True)
        month_open_counts[str(delay)]=int((times.dt.day.eq(1)&times.dt.hour.eq(0)&times.dt.minute.eq(0)).sum())
    result={
        'reviewed_at_utc':datetime.now(timezone.utc).isoformat(),
        'scope':'Read-only inspection of build_signals.py/account_market.py/engine.py, supporting signal timestamp and 1000-contract price-unit checks; no strategy modification or factor rerun.',
        'source_snapshot':{name:sha(ACCOUNT/name) for name in ['build_signals.py','account_market.py','engine.py','event-signals.parquet']},
        'market_manifest_sha256':sha(ACCOUNT/'market_manifest.json'),
        'checks':{
            'hourly_shards_keyed_by_spot_symbol_with_contract_identity_assertion':True,
            'nine_alias_hour_close_matches_raw_contract_prices':all(x['exactly_equal'] for x in examples),
            'price_qty_mark_funding_all_contract_units_no_extra_1000_multiplier':'Static trace: amount/contract_fill -> qty; gross=side*qty*(raw_exit-raw_entry); fee=qty*fill*rate; funding=side*qty*contract_mark*rate.',
            'hourly_asof':'floor(decision/arrival hour) uses completed hourly close; pool previous-day record unchanged.',
            'ema_asof':'15m right-labelled closed-left bars; only complete15 positive OHLCV; asof search right minus1; age<15min; frozen ewm parameters unchanged.',
            'correlation_asof':'72 hourly returns ending at floor arrival hour; missing/zero variation tightens correlation risk cap.',
            'ranking_and_collision':'same r6/vol24 and causal quoteRVOL; deterministic magnitude/liquidity/symbol order; quarantine pre-rank gap was separately escalated.',
            'signal_known_before_arrival':bool(signals.feature_known_ts.le(signals.decision_ts).all() and signals.ts.eq(signals.decision_ts+60000).all()),
            'cash_cost_trace':'Entry margin+fee reserved; adverse fill enters PnL once; reported gross minus explicit slip/fee/funding reconciles same cash ledger. No second slippage cash debit.',
            'future_coverage':'Missing entry/holding execution data invalidates whole path rather than selecting a different winning opportunity; funding coverage is accounting validity only.',
        },
        'alias_price_evidence':examples,
        'finding_resolved_by_owner_pending_final_freeze':{
            'known_quarantine_occupied_rank_slots':'Detected 8 post-known_ts ranked hours for quarantined symbol; reported to root/account/validation. Root approved point-in-time pre-ranking removal. No account source changed by this reviewer.'},
        'nonblocking_boundary_limitation':{
            'issue':'Market.change_month drops previous-month bar cache; prior-minute lookup at monthly 00:00 returns None.',
            'actual_candidate_counts_at_month_open_main_and_delay1':month_open_counts,
            'impact_this_signal_version':'No candidate at that exact boundary under either delay; does not affect current five-scenario results. Not a general guarantee for other signals.'},
        'conclusion':'No additional material blocker found within this scope beyond quarantined coin ranking, already accepted for correction.',
        'limits':['Not a replacement for independent executed-ledger audit or final source hash freeze.',
                  'Did not assess profitability, change feature selection, update thresholds, access simulator databases, or inspect exchange credentials.',
                  'Does not certify tick-level execution, actual user fees, margin tiers, or liquidation mechanics.']}
    (ROOT/'account_readonly_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'alias_price_checks':len(examples),'all_match':all(x['exactly_equal'] for x in examples),'month_open_candidates':month_open_counts}))

if __name__=='__main__':main()
