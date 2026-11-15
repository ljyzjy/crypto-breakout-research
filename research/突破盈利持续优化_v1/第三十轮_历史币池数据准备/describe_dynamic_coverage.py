"""Compare archive-based daily candidates with the older fixed 18-contract pool."""
import json
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
old=json.loads((HERE.parent.parent/'突破胜率与净收益前瞻检验_v1'/'冻结研究方案.json').read_text(encoding='utf-8'))
fixed={x['contract'] for x in old['fixed_pool']}
def main():
    d=pd.read_parquet(HERE/'历史动态20币候选_仅数据排名.parquet')
    d['in_fixed_18']=d.symbol.isin(fixed)
    def has_sources(row):
        base=ROOT/'work'/('breakout_2024_expanded18' if row.year==2024 else 'breakout_november_2026')/'normalized'
        return all((base/f'{row.symbol}_{suffix}.parquet').exists() for suffix in ('klines','markPriceKlines','fundingRate'))
    d['has_three_local_source_files']=[has_sources(r) for r in d.itertuples(index=False)]
    out=[]
    for year,g in d.groupby('year'):
        daily=g.groupby('day').agg(candidates=('symbol','size'),fixed=('in_fixed_18','sum'),local=('has_three_local_source_files','sum'))
        by_symbol=g.groupby('symbol').size().sort_values(ascending=False)
        out.append({'year':int(year),'days':len(daily),'distinct_top20_candidates':int(g.symbol.nunique()),
                    'distinct_not_in_fixed_18':int(g.loc[~g.in_fixed_18,'symbol'].nunique()),
                    'mean_fixed18_in_daily_top20':float(daily.fixed.mean()),
                    'min_max_fixed18_in_daily_top20':[int(daily.fixed.min()),int(daily.fixed.max())],
                    'mean_with_three_local_files':float(daily.local.mean()),
                    'symbols_most_frequently_ranked':[{'symbol':s,'days':int(n)} for s,n in by_symbol.head(10).items()]})
    d.to_parquet(HERE/'历史候选与旧币池覆盖.parquet',index=False)
    report={'periods':out,'fixed18':sorted(fixed),
            'note':'File presence and archive ranks are necessary data pointers, not proof of complete minute coverage, historical eligibility, or profitable trades.'}
    (HERE/'历史候选与旧币池覆盖.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE30_COVERAGE',json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
