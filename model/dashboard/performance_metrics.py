"""Presentation-only account CAGR; never modify frozen simulation outputs."""
from datetime import date
import math

def enrich(row):
    r=dict(row)
    if not r.get('start') or not r.get('end'):return r
    days=(date.fromisoformat(r['end'])-date.fromisoformat(r['start'])).days+1
    initial=float(r.get('initial',1000))
    final=float(r.get('final_equity',initial*(1+r['return_pct']/100)))
    annual=None
    reason='不足一年，仅展示区间收益'
    if not r.get('valid_for_comparison',True):reason='持仓价格数据缺失，年化不用于比较'
    elif days>=365 and initial>0 and final>=0:
        annual=math.expm1(math.log(final/initial)*365/days)*100 if final else -100.
        reason=f'{days} 个自然日 · 账户净值几何年化'
    r.update(annualized_return_pct=annual,elapsed_days=days,annualized_note=reason,
             annualized_basis='(final_equity / initial) ** (365 / inclusive_calendar_days) - 1; includes idle cash and all simulated costs')
    return r

def enrich_many(rows):return [enrich(r) for r in rows]
