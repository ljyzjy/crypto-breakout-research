"""Extend the existing causal daily liquidity ranking to 40 records."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;DAY=86_400_000
def main():
    p=PARENT/'第三十轮_历史币池数据准备';daily=pd.read_parquet(p/'公开日线已校验成交额.parquet')
    old=pd.read_parquet(p/'历史动态20币候选_仅数据排名.parquet');q=json.loads((p/'历史动态币池数据质量.json').read_text(encoding='utf-8'))
    assert not q['archive_errors'] and not daily.duplicated(['symbol','open_time']).any()
    daily.loc[~daily.valid_for_ranking,'quote_volume']=np.nan
    wide=daily.pivot(index='open_time',columns='symbol',values='quote_volume').sort_index();frames=[]
    for day in sorted(old.day.unique()):
        t=int(pd.Timestamp(day,tz='UTC').timestamp()*1000);prior=wide.reindex(np.arange(t-30*DAY,t,DAY,dtype=np.int64))
        ready=prior.notna().all(axis=0);sums=prior.loc[:,ready].sum(axis=0)
        x=pd.DataFrame({'symbol':sums.index,'past_30d_quote':sums.to_numpy(float)})
        x=x.sort_values(['past_30d_quote','symbol'],ascending=[False,True]).head(40).reset_index(drop=True)
        x['rank']=np.arange(1,len(x)+1);x['eligible_symbols_that_day']=int(ready.sum());x['day']=day;x['year']=int(day[:4])
        previous=old[old.day.eq(day)].sort_values('rank')
        assert x.head(20).symbol.tolist()==previous.symbol.tolist()
        assert np.allclose(x.head(20).past_30d_quote,previous.past_30d_quote,rtol=1e-11,atol=1e-6)
        frames.append(x)
    out=pd.concat(frames,ignore_index=True);assert not out.duplicated(['day','symbol']).any()
    out.to_parquet(HERE/'历史前40候选_仅事前日成交额.parquet',index=False)
    oldpairs={(int(r.year),r.symbol) for r in old.itertuples(index=False)}
    newpairs={(int(r.year),r.symbol) for r in out.itertuples(index=False)}
    info={'days':out.day.nunique(),'candidate_rows':len(out),'symbol_year_pairs':len(newpairs),
          'new_symbol_year_pairs':len(newpairs-oldpairs),'old_top20_all_days_reproduced':True,
          'per_year_symbols':{str(k):int(v) for k,v in out.groupby('year').symbol.nunique().to_dict().items()},
          'plan_sha256':hashlib.sha256((HERE/'冻结数据规则.json').read_bytes()).hexdigest(),
          'note':'Daily data preparation only; minute availability, trading signal and performance are not inferred.'}
    (HERE/'前40候选数据清点.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_TOP40',json.dumps(info,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
