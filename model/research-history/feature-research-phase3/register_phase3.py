"""Run once, before new outcome labels; freeze the Phase 3 amendment."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib
P=Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
out=P/'protocol.json'
assert not out.exists(), 'Never overwrite a frozen protocol'
obj={
 'id':'phase3-chronological-increment-account-v1',
 'created_utc':datetime.now(timezone.utc).isoformat(),
 'new_outcomes_seen_at_registration':False,
 'classification':'Already researched historical data; chronological retrospective exploration, not pristine out-of-sample or formal future confirmation.',
 'original_simulator_changed':False,'live_execution':False,'leverage_cap':1,
 'amendments_to_phase1':[
  'Split the already seen 481-day development history into train/screen/account evaluation; the reserved future 90+90-day protocol remains unactivated and unchanged.',
  'One refit on Jan-Jun is allowed only for this historical account evaluation, after Apr-Jun group selection. This is an explicit amendment, not the original no-refit forward protocol.',
  'Replace tentative strategy branch names with at most three predeclared overlays on a shared matured-event baseline: joint alpha, F3 half-risk, combined.',
  'Event baseline waits until five bars after initial breakout close. This changes original uncapped entry; only overlay versus its matched event baseline isolates feature effects.',
  'The 300-day account evaluation has no reported/validated CAGR. Report full-calendar net return and cash/halt days.'
 ],
 'splits':{
  'train':{'start':'2025-01-01T00:00:00Z','end_exclusive':'2025-04-01T00:00:00Z','days':90},
  'screen':{'start':'2025-04-01T00:00:00Z','end_exclusive':'2025-07-01T00:00:00Z','days':91},
  'evaluation':{'start':'2025-07-01T00:00:00Z','end_exclusive':'2026-04-27T00:00:00Z','days':300},
  'purge_minutes':65,'label_end_strictly_before_segment_end':True,'no_random_split':True,
  'refit':'Selected alpha union and selected F3 risk models fit once on event rows Jan-Jun; all label ends strictly before Jul 1. No later refit.'
 },
 'data':{'phase2_manifest_sha256':'97f618f9874237a957437fc6e0a996c8c8d8f0fa4117e9ded91e18eb66a834ea',
  'market_manifest_sha256':sha(P/'account/market_manifest.json'),
  'source':'Same 60 mapped perpetual contracts/481 historical daily pools; 509 warmup trade files plus four original post-exit trade month buffers; 433 mark and 434 funding files. No new later outcome period.',
  'features':'Unchanged Phase2 features.py and per-group masks; 12 features in 6 groups, no 12-way screening intersection.',
  'missing':'No price/volume/funding fill. Labels missing ex post only affect paired statistical loss; never filter account entries using future completeness.',
  'paper':'No access or write to current simulator database; protect previous code/config and Phase1/2 outputs.'},
 'labels':{'entry':'decision_ts + 1 minute open','exit':'entry + H minutes open',
  'horizons_minutes':[15,30,60],'primary_horizon':30,
  'return':'side * log(exit_open/entry_open) * 10000; net proxy gross minus fixed 20bp, excludes historical funding and is not account PnL',
  'mae_mfe':'Nonnegative maximum adverse/favorable directional log excursion in bp, using completed holding minutes [entry,exit).',
  'validity':'All holding-minute OHLCV valid per Phase2; entry/exit open finite positive; exit-bar subsequent HLC/volume not required. Labels unavailable/invalid retain reasons.'},
 'group_test':{'controls':['intercept','side*r6','side*btc_r6','vol24','log1p(quote_rvol)','utc_hour_sin','utc_hour_cos','coin_fixed_effect'],
  'F1':{'cohort':'clock','add':['side*residual6'],'target':'return'},
  'F2':{'cohort':'clock','add':['efficiency6','concentration6'],'target':'return'},
  'F3':{'cohort':'clock','add':['rv_relative60','range_atr'],'target':'MAE_risk_only'},
  'F4':{'cohort':'event','add':['boundary_distance','outside_fraction5'],'target':'return'},
  'F5':{'cohort':'event','add':['drawdown_atr','recovery_fraction'],'target':'return'},
  'F6':{'cohort':'clock','add':['log1p(count_rvol)'],'target':'return'},
  'fit':'Paired identical row IDs within group, OLS training-only median/IQR scale; true constants no DOF, zero IQR nonconstant scale 1; SVD rcond 1e-12; unknown coin FE zero and separately counted; no outcome winsorization.',
  'loss':'Baseline squared error minus enhanced squared error; average observations within coin-day, equal coins within UTC day, then equal observed days.',
  'bootstrap':{'block_calendar_days':7,'joint_across_coins':True,'replicates':2000,'seed':20261113,'retain_empty_calendar_days':True,'p':'one-sided centered-null (1+null>=observed)/(B+1)','ci':'uncentered percentile 95%'},
  'selection':'30m screen loss improvement >0, new effective design rank>0, minimum samples satisfied, and Holm six-test adjusted p<=0.05. Missing test gets p=1. Historical exploratory gate, not formal unseen confirmation.',
  'minima':{'observations':200,'active_days':30,'active_UTC_weeks':8,'coins':5,'feature_coverage':0.8},
  'diagnostics':'15/60m always reported, never select/replace primary based on better horizon. No recursive subset or threshold search.'},
 'account_baseline':{
  'source':'Phase2 measured eligible nonquarantined event, no future label mask.',
  'decision':'t0 open +6 minutes, after initial and five subsequent bars complete; direction close beyond frozen B.',
  'eligibility':'Rebuild hourly rank and closed 15m EMA from common warmed minute data; quote RVOL>=1.5, top3 long and bottom3 short by r6/vol24, daily prior liquidity order and symbol tie. Require matching closed EMA20 direction/slope at decision and arrival. Phase2 strict complete 6h definition used.',
  'ema':'15m complete positive OHLCV bars; ewm span20 adjust=False min_periods20 ignore_na=False; never use unclosed bar.',
  'stop':'Long min low, short max high from t0 through last completed decision bar, with 0.1 frozen ATR margin.',
  'arrival':'decision+1minute+cost-scenario delay; adverse entry price drift >0.25ATR rejected; stop distance >0 and <=1.5ATR; 2*distance/price>=0.006 at signal and arrival.',
  'collision_order':'absolute r6/vol24 descending, prior daily pool liquidity rank, symbol lexicographic; deterministic same across candidates.',
  'exit':'2R target, stop-first if both within minute, adverse gap/open fills; max60min hold; Beijing22:00 no new entries,23:55 flat;60min symbol cooldown and next-minute global wait after exit.',
  'risk':'Initial1000USDT; .25% per trade, .5% aggregate planned loss; corr72h>.8 or missing caps aggregate .25%; max2 positions, each notional<=.5equity,total entry notional<=1equity,order<=.1% prior-minute quote; 10USDT approximate min order.',
  'protection':'Daily1.5% loss pause; peakDD5% halves new risk; peakDD8% permanent halt with next-minute flatten; high-water never reset. Full calendar retained, halt is not demonstrated continuous DD control.',
  'execution_limits':'No historical L2/tick-step filters or exchange liquidation/margin-tier reconstruction. 1x notional cap may drift; no second-level execution claim.'},
 'candidates':{
  'common_opportunity_mask':'All selected account models required inputs finite at decision; baseline and all overlays share this ex-ante mask; no label validity or future market coverage. Unrestricted event baseline additionally reports coverage effect.',
  'joint_alpha':'If any of F1,F2,F4,F5,F6 pass: union their additions in one event OLS, paired baseline/enhanced rows Jan-Jun; trade only enhanced 30m gross prediction>20bp AND enhanced-baseline prediction>0. No subsets.',
  'risk_half':'If F3 passes: independent paired event MAE OLS Jan-Jun; raw enhanced-baseline MAE>0 -> planned per-trade risk times0.5, otherwise1. No clipping or leverage increase.',
  'combined':'Only if both alpha and F3 pass and refits evaluable; apply the same alpha gate and risk multiplier.',
  'refit_validity':'Same observation/day/week/coin minima and added effective rank required. Failure means candidate unevaluable, not replacement rule.',
  'transport':'Clock-selected groups transferred to events are unvalidated transfer hypotheses; final account comparison evaluates that transfer once.',
  'none_pass':'Run baselines and retain all failed tests. Do not invent an alpha candidate.'},
 'cost_scenarios':[
  {'id':'main','fee':.0005,'slippage':.0005,'delay_minutes':0},
  {'id':'fee2','fee':.001,'slippage':.0005,'delay_minutes':0},
  {'id':'fee3','fee':.0015,'slippage':.0005,'delay_minutes':0},
  {'id':'slip2','fee':.0005,'slippage':.001,'delay_minutes':0},
  {'id':'delay1','fee':.0005,'slippage':.0005,'delay_minutes':1}],
 'cost_notes':'Same original assumptions: each-side notional fee+adverse price slip; historical funding separate, ambiguous entry/exit settlement only debit. Each scenario recalculates size using its costs. Fixed .006 space gate. 0.05% taker is assumed public example, not verified user VIP/historical account fee; slip is an estimate.',
 'account_success':'Main net>0, PF>1, >=100 closed trades; all five scenarios valid and net>0, close DD<=15%, intrabar stressDD<=15%; also compare net gain versus matched baseline. No annualization under365 days. All failures reported.',
 'audit':'Check label maturity, paired IDs, future mutation invariance, fit timestamps, source hashes, all scenario ledger reconciliation, exposure and cash/halt days, funding and samebar handling. Fix implementation bugs with logged reason; no performance-driven changes.'
}
out.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
freeze={'created_utc':obj['created_utc'],'protocol_sha256':sha(out),'market_manifest_sha256':sha(P/'account/market_manifest.json'),'phase1_registration_sha256':sha(P.parent/'feature-research-phase1/research_registration.json'),'phase2_freeze_manifest_sha256':sha(P.parent/'feature-research-phase2/freeze_manifest.json'),'new_outcomes_seen':False,'boundary':'Local integrity record, not third-party timestamp; component code frozen separately before real outcome runs.'}
(P/'registration_freeze.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(freeze))
