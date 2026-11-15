"""Check fees, funding timing, missing data and conservative liquidation proxy."""
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from evaluate_unit_paths import risk_and_funding
HERE=Path(__file__).resolve().parent
class Market:
    def __init__(self):
        self.funding={'X':{0:[(2000,.0001)]}};self.missing=False;self.covered=True;self.low=99.
    def bar(self,c,t,mark=False):
        if self.missing:return None
        return np.array([100.,101.,self.low,100.])
    def funding_ok(self,c,t):return self.covered
r=SimpleNamespace(side=1,entry_ts=1000,exit_ts=61000,contract='X',entry_fill=100.05,exit_fill=101.)
m=Market();q=risk_and_funding(r,m);qty=1/r.entry_fill
expected_funding=qty*100*.0001
expected=qty*(r.exit_fill-r.entry_fill)-.0005-qty*r.exit_fill*.0005-expected_funding
assert q['risk_status']=='verified' and not q['liq_proxy'] and abs(q['funding']-expected_funding)<1e-14
assert abs(q['net_per_unit_notional']-expected)<1e-14
m.low=90.;assert risk_and_funding(r,m)['liq_proxy']
m.missing=True;assert risk_and_funding(r,m)['risk_status']=='missing_mark'
m.missing=False;m.covered=False;assert risk_and_funding(r,m)['risk_status']=='missing_funding_coverage'
m.covered=True;m.low=99.;m.funding={'X':{0:[(1000,.0001)]}}
short=SimpleNamespace(**{**r.__dict__,'side':-1})
assert risk_and_funding(short,m)['funding']==0.,'do not count uncertain boundary credit'
out={'fees_and_funding_recomputed':True,'minute_mark_proxy_can_flag':True,'missing_mark_and_funding_are_errors':True,
     'boundary_funding_credit_is_not_assumed':True}
(HERE/'资金费与强平代理合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('SECONDS29_RISK_SYNTHETIC_PASS',json.dumps(out),flush=True)
