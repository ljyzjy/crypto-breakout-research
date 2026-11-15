"""Reproduce the real-history prefix and perturbation checks without changing rules."""
import json
import engine

data=engine.load()
full=engine.simulate(data,'2023-01-01','2026-10-31')
checks=[]
for cut in ['2023-06-30','2024-06-30','2025-06-30']:
    prefix=engine.simulate({s:d.loc[:cut] for s,d in data.items()},'2023-01-01',cut)
    assert [t for t in full['trace'] if t['date']<=cut]==prefix['trace']
    assert [o for o in full['orders'] if o['date']<=cut]==[o for o in prefix['orders'] if o['reason']!='window_end']
    checks.append({'cutoff':cut,'decision_and_order_prefix':'PASS'})
changed={s:d.copy() for s,d in data.items()}
for d in changed.values():d.loc['2025-01-01':,['open','high','low','close','quote_volume']]*=100
mutated=engine.simulate(changed,'2023-01-01','2026-10-31')
assert [t for t in full['trace'] if t['date']<'2025-01-01']==[t for t in mutated['trace'] if t['date']<'2025-01-01']
formation=json.loads((engine.ROOT/'universe.json').read_text())
for s,d in data.items():
    expected=next(r['median_quote_volume'] for r in formation['candidates'] if r['symbol']==s)
    actual=float(d.loc['2022-12-01':'2022-12-31'].quote_volume.median())
    assert abs(actual-expected)/max(1,expected)<1e-6,(s,actual,expected)
print(json.dumps({'real_prefix_checks':checks,'future_mutation':'PASS','formation_data_reconciliation':'PASS'},indent=2))
