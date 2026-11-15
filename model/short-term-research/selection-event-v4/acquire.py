import importlib.util
from pathlib import Path
import event_engine as e

def make_plan():
    symbols=set();plan=set();daily={}
    for row in e.parent.hourly_history('control'):
        daily.setdefault(row['date'][:10],set()).update(p['symbol'] for p in row['ranked'])
    first={}
    for day,assets in daily.items():
        for s in assets:
            symbols.add(s)
            first[s]=min(first.get(s,day),day)
    # Positions can remain after leaving the selection pool, so do not restrict
    # execution coverage to months in which a coin was a candidate.
    for s,day in first.items():
        start=(e.pd.Timestamp(day)-e.pd.Timedelta(days=1)).strftime('%Y-%m')
        for month in e.pd.period_range(start,'2026-04',freq='M').astype(str):plan.add((s,month))
    for s in ('BTCUSDT','ETHUSDT'):
        symbols.add(s)
        for m in e.pd.period_range('2024-12','2026-04',freq='M').astype(str):plan.add((s,m))
    e.base.dump(e.ROOT/'coverage-plan.json',dict(symbols=sorted(symbols),months=sorted(plan)))
    print('All replacement candidates',len(symbols),'asset-months',len(plan),flush=True)
    return symbols,plan

def main():
    path=e.parent.ROOT/'acquire_replacements.py'
    spec=importlib.util.spec_from_file_location('replacement_acquisition_v4',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.e=e;module.original=e.parent;module.a.make_plan=make_plan
    module.main()

if __name__=='__main__':main()
