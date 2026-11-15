"""Synthetic checks for daily ranking availability and no same-day lookahead."""
import json
from pathlib import Path
import pandas as pd
from download_rank_daily import build_ranks,DAY
HERE=Path(__file__).resolve().parent
dates=pd.date_range('2026-04-01','2026-05-02',freq='D',tz='UTC')
rows=[]
for symbol in ['AUSDT','BUSDT']:
    for date in dates:
        amount=100. if symbol=='AUSDT' else 90.
        if symbol=='BUSDT' and date==pd.Timestamp('2026-05-01',tz='UTC'):amount=10_000.
        ts=int(date.timestamp()*1000)
        rows.append({'symbol':symbol,'open_time':ts,'close_time':ts+DAY-1,'quote_volume':amount,'valid_for_ranking':True})
d=pd.DataFrame(rows);r=build_ranks(d)
one=r[r.day.eq('2026-05-01')].sort_values('rank');two=r[r.day.eq('2026-05-02')].sort_values('rank')
assert list(one.symbol)==['AUSDT','BUSDT'] and list(two.symbol)==['BUSDT','AUSDT']
remove=int(pd.Timestamp('2026-04-15',tz='UTC').timestamp()*1000)
incomplete=d[~(d.symbol.eq('AUSDT')&d.open_time.eq(remove))]
missing=build_ranks(incomplete);assert 'AUSDT' not in missing[missing.day.eq('2026-05-01')].symbol.tolist()
out={'uses_previous_30_completed_days':True,'same_day_future_volume_not_used':True,'missing_day_excludes_rank':True}
(HERE/'日线排名合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIVERSE30_RANK_SYNTHETIC_PASS',json.dumps(out),flush=True)
