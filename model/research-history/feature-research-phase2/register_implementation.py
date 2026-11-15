"""Pin technical details before feature quality results. No market or outcome reads."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
OUT=Path(__file__).resolve().parent
P1=OUT.parent/'feature-research-phase1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
registration={
 'id':'feature-intraday-foundation-v1-implementation-1',
 'registered_at_utc':datetime.now(timezone.utc).isoformat(),
 'parent_registration_sha256':sha(P1/'research_registration.json'),
 'scope':'Historical warmup repair, immutable data version, twelve feature implementation, causal availability/coverage/stability checks and matched observation masks. No forward-return labels, predictive fitting or account backtests in this phase.',
 'old_results_seen':True,'new_feature_quality_results_seen_at_registration':False,
 'source_time':'All minute timestamps are UTC open milliseconds. A complete minute is available no earlier than open+60000; data receive/processing latency remains unobserved.',
 'decisions':'Clock decisions on UTC hour/half-hour. Latest complete hourly factors may be used at half-hour. Event t0 is breakout minute OPEN; t0+5 bar finishes at t0+6 minutes, the first event-feature decision timestamp.',
 'f3_halfhour_clarification':'rv_relative60 uses the trailing60 completed minute returns at each decision time; reference windows end at the identical UTC hour-and-minute phase on each of the preceding20 days. No unclosed hourly window is used at a half-hour.',
 'atr_clarification':'range_atr denominator is latest completed15m ATR14 available at the OPEN of the measured1m. Event A uses same rule at breakout minute OPEN and is frozen. Incomplete/missing required bars are not filled.',
 'event_causality':'First eligible fresh break of prior20 completed minute extreme; retain earliest per-symbol event within60 minutes, regardless of outcome. B/A and origin immutable. Evaluate exactly five subsequent completed bars. Failed/re-entered boundaries remain events; missing data or loss of eligibility at decision is explicit, not removed based on subsequent return.',
 'normalization':'No outcome fitting/return optimization. F1 normalization uses registered past-only OLS and residual std. Stability sensitivity only5h/7h background and15m/25m boundary one dimension at a time.',
 'eligibility':'Original point-in-time daily pools and mapping; original observed quarantine. Preserve missing and exclusion rows. Daily pool changes atUTC date boundary using previous complete day only.',
 'matched_masks':'For each group independently, baseline and enhanced use the identical observation ID set after shared eligibility, decision-time availability, common controls, registered group variables and65min tail purge. Do not intersect all six groups. Keep both kept and excluded masks and missing reasons.',
 'common_controls':['r6','btc_r6','vol24','quote_rvol'],
 'group_columns':{'F1':['r6','residual6'],'F2':['efficiency6','concentration6'],'F3':['rv_relative60','range_atr'],'F4':['boundary_distance','outside_fraction5'],'F5':['drawdown_atr','recovery_fraction'],'F6':['quote_rvol','count_rvol']},
 'purge':'Measured decision_ts, not breakout t0; require decision_ts < end_exclusive-65min. Later return-label construction must independently verify each label end < boundary. No labels are constructed now.',
 'coverage':'Report all original clock/event opportunity counts, feature-only availability, group/common-control availability, matched counts, calendar/symbol distributions and attrition reasons. Legacy residual comparison uses exactly old universe-hour keys before interpreting change.',
 'quality_threshold_source':'Parent registration coverage0.80/sample200/active days30/weeks8/symbols5; no new minimum stability correlation/Jaccard is selected after seeing results. Report sensitivity continuously without claiming profitability.',
 'no_future_metadata_filter':'Archive completeness discovered now is an audit outcome, not a feature available to an historical trader. Do not pre-exclude histories based on future archive gaps. Keep original known-time quarantine.',
 'forward_started':False,'paper_changed':False,'website_changed':False,
 'amendment_policy':'Any technical corrections are recorded before final freezing, with reason and scope. No correction may be selected on future PnL, which is not computed.'
}
target=OUT/'implementation_registration.json'
assert not target.exists(),'Do not silently overwrite registration'
target.write_text(json.dumps(registration,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'id':registration['id'],'sha256':sha(target)}))
