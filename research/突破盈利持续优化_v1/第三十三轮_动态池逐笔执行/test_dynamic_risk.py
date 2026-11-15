"""Synthetic unit ledger, funding timing, missing archive and leverage risk."""
import json
from pathlib import Path
from types import SimpleNamespace
from settle_dynamic_paths import settle
HERE=Path(__file__).resolve().parent
r=SimpleNamespace(side=1,entry_ts=1000,exit_ts=61000,entry_fill=100.,exit_fill=101.,contract='X',variant='normal_2r_20x')
marks={('X',0):{'open':100.,'high':101.,'low':99.,'close':100.},
       ('X',60000):{'open':100.,'high':101.,'low':99.,'close':100.}}
funds={('X','1970-01'):[{'ts':30000,'funding_interval_hours':8,'last_funding_rate':.0001},
                        {'ts':28830000,'funding_interval_hours':8,'last_funding_rate':.0001}]}
sources={('markPriceKlines','X','1970-01'):'verified',('fundingRate','X','1970-01'):'verified'}
a=settle(r,marks,funds,sources);expected=(101.-100.)/100.-.0005-1.01*.0005-.0001
assert a['risk_status']=='verified' and abs(a['net_per_unit_notional']-expected)<1e-14 and not a['liq_proxy']
marks[('X',0)]['low']=96.;assert settle(r,marks,funds,sources)['liq_proxy']
r.variant='normal_2r_10x';assert not settle(r,marks,funds,sources)['liq_proxy']
sources[('fundingRate','X','1970-01')]='checksum_404';assert settle(r,marks,funds,sources)['risk_status']=='missing_funding_archive'
out={'entry_exit_fees_and_funding':True,'mark_proxy_differs_by_leverage':True,'missing_funding_not_zero_filled':True}
(HERE/'动态池强平与资金费合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIVERSE33_RISK_SYNTHETIC_PASS',json.dumps(out),flush=True)
