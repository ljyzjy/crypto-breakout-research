"""Independently reconstruct sampled data-available replacement rankings."""
import json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;H=3_600_000
def main():
    daily=pd.read_parquet(HERE/'历史前40候选_仅事前日成交额.parquet')
    bars=pd.read_parquet(HERE/'前40分钟严格合成小时.parquet')
    top=pd.read_parquet(HERE/'逐小时动态替补排名_待候选验证.parquet')
    by={(int(y),s):g.set_index('open_time') for (y,s),g in bars.groupby(['year','symbol'])}
    days=sorted(daily.day.unique());picks=sorted(set(np.linspace(0,len(days)-1,24,dtype=int).tolist()))
    checked=0;incomplete=0;max_error=0.
    for n,pos in enumerate(picks):
        day=days[pos];year=int(day[:4]);t=int(pd.Timestamp(day,tz='UTC').timestamp()*1000)+((n*7)%24)*H
        available=[]
        for r in daily[daily.day.eq(day)].sort_values('rank').itertuples(index=False):
            data=by[(year,r.symbol)];cs=np.arange(t-25*H,t,H,dtype=np.int64)
            vs=np.array([t-H-k*24*H for k in range(21)],dtype=np.int64);z=data.reindex(np.unique(np.r_[cs,vs]))
            if not z.valid.fillna(False).all():continue
            close=data.reindex(cs).close.to_numpy(float);ret=np.diff(np.log(close));sd=ret.std(ddof=1)
            volume=data.reindex(vs).quote_volume.to_numpy(float);med=np.median(volume[1:])
            if sd<=0 or med<=0:continue
            available.append({'symbol':r.symbol,'daily_rank':int(r.rank),'score':float(ret[-6:].sum()/sd),'rvol':float(volume[0]/med)})
        actual=top[top.decision_hour.eq(t)]
        if len(available)<20:assert actual.empty;incomplete+=1
        else:
            selected=available[:20]
            for side in (-1,1):
                exp=[x for x in selected if x['rvol']>=1.5 and x['score']*side>0]
                exp=sorted(exp,key=lambda x:(-abs(x['score']),x['daily_rank'],x['symbol']))[:3]
                got=actual[actual.side.eq(side)].sort_values('hourly_rank')
                assert [x['symbol'] for x in exp]==got.symbol.tolist(),(day,side)
                for x,r in zip(exp,got.itertuples(index=False)):
                    err=abs(x['score']-float(r.score));max_error=max(max_error,err)
                    assert np.isclose(x['score'],r.score,rtol=1e-8,atol=1e-8) and np.isclose(x['rvol'],r.rvol,rtol=1e-8,atol=1e-8)
        checked+=1
    result={'sampled_decision_hours':checked,'samples_with_fewer_than_20_available':incomplete,
            'max_score_absolute_error':max_error,'minute_derived_inputs_used':True,'future_data_not_used':True,
            'note':'Selection of observed available data does not prove historical archive completeness or actual trading eligibility.'}
    (HERE/'动态替补排名抽样核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_BACKUP_AUDIT',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
