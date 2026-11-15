"""Select prior signals using only information known by planned order submission."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'突破胜率与净收益前瞻检验_v1'
spec=importlib.util.spec_from_file_location('maker_forward_context',PRIOR/'forward_research.py')
forward=importlib.util.module_from_spec(spec);sys.modules[spec.name]=forward;spec.loader.exec_module(forward)
market=forward.FixedMarket();guard=forward.FixedGuard(market)
signals=pd.read_parquet(PRIOR/'first_signals.parquet')
assert len(signals)==101 and signals.observation_id.is_unique
reasons=[]
for s in signals.itertuples(index=False):
    t=int(s.ts); reason='eligible_for_order'
    if (t//60_000+480)%1440>=1320:reason='late_day'
    elif not guard.eligible(s.symbol,int(s.side),t):reason='rank_or_trend_changed'
    else:
        prior=market.bar(s.contract,t-60_000);mark=market.bar(s.contract,t-60_000,True)
        if prior is None or mark is None or prior[4]<=0 or not np.isfinite(prior[5]) or prior[5]<=0:reason='prior_market_data_unknown'
    reasons.append(reason)
signals['known_eligibility']=reasons
signals.to_parquet(HERE/'全部候选与事前资格.parquet',index=False)
eligible=signals[signals.known_eligibility.eq('eligible_for_order')].copy()
eligible.to_parquet(HERE/'计划下单候选.parquet',index=False)
report={'total_candidates':len(signals),'eligible_for_order':len(eligible),
        'known_status_counts':signals.known_eligibility.value_counts().to_dict(),
        'boundary':'No account funding/positions or future trade outcomes used to establish eligibility.'}
(HERE/'候选资格核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('CANDIDATES_READY',json.dumps(report,ensure_ascii=False),flush=True)
