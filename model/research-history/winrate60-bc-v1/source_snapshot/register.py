"""Register a single B/C experiment before computing its outcomes."""
from pathlib import Path
from datetime import datetime, timezone
import json, hashlib

BASE=Path(__file__).resolve().parents[2]
OUT=BASE/'outputs/winrate60-bc-v1'
P3=BASE/'outputs/feature-research-phase3'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,d): Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'protocol.json').exists(), 'Never overwrite registration'
    old=json.loads((P3/'protocol.json').read_text(encoding='utf-8'))
    protocol={
      'id':'winrate60-bc-v1','registered_utc':datetime.now(timezone.utc).isoformat(),
      'historical_outcomes_seen_before_design':True,'new_B_C_outcomes_seen':False,
      'scope':'Chronological retrospective research on previously inspected history; not pristine out-of-sample confirmation.',
      'splits':{'train':['2025-01-01','2025-04-01'],'calibration':['2025-04-01','2025-07-01'],'evaluation':['2025-07-01','2026-04-27']},
      'purge':'decision + 65 minutes strictly before train/calibration end; realized label exit also strictly before end; no random split.',
      'refit':'None. Fit base model once Jan-Mar; fit calibration/payoff once Apr-Jun; freeze all before July evaluation.',
      'data':{'phase2_manifest_sha256':sha(BASE/'outputs/feature-research-phase2/data/manifest.json'),'market_manifest_sha256':sha(P3/'account/market_manifest.json'),'baseline_signals_sha256':sha(P3/'account/event-signals.parquet'),'phase3_protocol_sha256':sha(P3/'protocol.json')},
      'B':'Identical matured-breakout baseline opportunities and entry/exit; accept calibrated net-win probability >=0.65 and estimated net expectancy >0.',
      'C':{'seeds':'Same frozen causal first-breakout event queue, 60-minute dedup. Ignore future event measurement validity; use only t0 facts and closed bars at the new decision.',
        'touch':'After initial breakout bar, first bar overlapping [B-0.25A,B+0.25A].',
        'failure':'Cancel if any subsequent completed close is >0.25A on the wrong side of B; cancel at first missing/invalid bar.',
        'confirm':'Strictly later bar than touch; long close > B and prior bar high; short close < B and prior bar low. First confirmation only.',
        'deadline':'Confirmation close no later than initial breakout close +15min.',
        'entry':'Confirmation close timestamp +1min open; same arrival gates/rank/EMA as B.',
        'stop':'Extreme from initial breakout through confirmation bar, plus 0.1 frozen ATR margin; same 1.5ATR and 0.006 roundtrip space gates.',
        'filter':'Same fixed architecture/hyperparameters as B; separately trained on C-specific execution labels.'},
      'features':['aligned_r6','aligned_r24','aligned_btc24','aligned_residual6','residual_missing','is_btc','boundary_distance','outside_fraction','drawdown_atr','recovery_fraction','taker_imbalance3','price_change3_atr','stop_cost_ratio','log_quote_rvol','atr_fraction','side_feature'],
      'feature_definitions':{
        'aligned_r6':'side*r6/(sqrt(6)*vol24), closed-hour inputs',
        'aligned_r24':'side*sum(last24 complete hourly log returns)/(sqrt(24)*vol24)',
        'aligned_btc24':'side*BTC sum(last24 complete hourly log returns)/(sqrt(24)*BTC vol24)',
        'residual':'Frozen Phase2 lagged-beta residual6, direction aligned; optional missing, training median imputed with flag; BTC structural missing flagged.',
        'path':'All observed bars t0 through decision: distance=(side*(lastclose-B))/A; outside_fraction of post-break closes >=0.25A; drawdown from favorable extreme; recovery from lowest oriented low strictly after last extreme bar (0 if none).',
        'flow':'side*(2*sum(taker_buy_quote_volume)-sum(quote_volume))/sum(quote_volume) over 3 completed minutes; price_change3_atr=side*(lastclose-firstopen)/A.',
        'cost':'0.002/(side*(decisionclose-stop)/decisionclose); not funding forecast.',
        'activity':'log1p(latest closed-hour quote RVOL); atr_fraction=A/decisionclose; side_feature=side.'},
      'missing':'No fill prices/volume; optional residual median + flag only. Any other missing feature abstains. No future outcome availability used to prefilter evaluation signals.',
      'labels':'Independent executable unit-notional opportunities, main-cost adverse entry/exit, 2R, structural stop, stop-first, gaps, 60min/day close, actual funding. Entry eligibility/gates checked on arrival. Nonexecuted/unavailable labels retained with reasons. Portfolio-dependent pauses cannot label independent opportunities; final account uses unchanged protections and all exits count.',
      'model':{'type':'L2 logistic regression','objective':'sum Bernoulli negative log likelihood +0.5*sum(non-intercept coefficients squared)','class_reweight':False,'standardization':'training median/IQR; zero IQR uses1; clip standardized inputs to [-10,10]','optimizer':'scipy L-BFGS-B maxiter2000 ftol1e-12 gtol1e-8','calibration':'Platt a*raw_logit+b, a>=0, penalty0.5*(a-1)^2; no probability threshold search','min_train':200,'min_train_each_class':30,'min_calibration':100,'min_calibration_each_class':20},
      'gate':{'probability':0.65,'expected_net_R':'p*calibration_mean_positive_net_R -(1-p)*calibration_mean_absolute_nonpositive_net_R >0. Fixed global conditional payoff proxy; not claimed individual conditional guarantee.','cost_stress':'Keep main-cost model and gate fixed in all stress scenarios; re-execute account under stressed costs, never recalibrate.'},
      'account':old['account_baseline'],'cost_scenarios':old['cost_scenarios'],'cost_notes':old['cost_notes'],
      'evaluation':'B and C account runs all five scenarios, same 300 days. Reuse and reproduce A main baseline. No C unfiltered optimized account; report unfiltered opportunity diagnostics separately and do not confuse them with portfolio results.',
      'success':{'primary':'Main valid, net win rate>=60%, net PnL>0, PF>1, close and intrabar stress DD<=15%, >=100 completed trades and >=30 active UTC days.','stress':'Separately report all five costs; do not replace main.','uncertainty':'7-calendar-day moving block bootstrap of account trade exits, 2000 draws seed20261113; retained zero-trade days; no meaningful CI with <30 active days or <100 trades.','empty':'Zero trades means unachieved/insufficient sample, never 100% win or success.'},
      'selection':'No threshold/horizon/model/coin/TP grid, no outcome-driven refit. Implementation bugs may be corrected with written reason and preserved attempts.',
      'leverage_cap':1,'paper_changed':False,'live_execution':False,
      'audit':'Source hashes before/after; exact B evaluation signal equality; feature future-prefix invariance; model temporal boundaries; independent sample labels versus engine; all account ledgers/funding; C touch<confirmation<entry.'
    }
    dump(OUT/'protocol.json',protocol)
    protected={}
    for name in ['feature-research-phase2','feature-research-phase3']:
        root=BASE/'outputs'/name
        for rel,item in json.loads((root/'freeze_manifest.json').read_text(encoding='utf-8'))['files'].items():
            protected[str((root/rel).resolve())]=item['sha256']
    previous=json.loads((P3/'protection_validation.json').read_text(encoding='utf-8'))
    dump(OUT/'registration.json',{'created_utc':protocol['registered_utc'],'protocol_sha256':sha(OUT/'protocol.json'),'protected_files':protected,'previous_protection':previous,'paper_database_accessed':False})
    print(json.dumps({'protocol_sha256':sha(OUT/'protocol.json'),'protected_files':len(protected)}))
