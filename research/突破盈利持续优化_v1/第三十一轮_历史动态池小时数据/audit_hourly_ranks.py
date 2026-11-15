"""Manual spot checks of closed-hour indicators and cross-sectional rank ordering."""
import json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;H=3_600_000
def main():
    daily=pd.read_parquet(PARENT/'第三十轮_历史币池数据准备'/'历史动态20币候选_仅数据排名.parquet')
    bars=pd.read_parquet(HERE/'历史候选小时行情_原始可验证.parquet')
    top=pd.read_parquet(HERE/'历史动态池小时动量前三_待分钟核验.parquet')
    by={(int(y),s):g.set_index('open_time') for (y,s),g in bars.groupby(['year','symbol'])}
    days=sorted(daily.day.unique());picks=sorted(set(np.linspace(0,len(days)-1,24,dtype=int).tolist()))
    checked=0;indicators=0;max_score=0.;max_rvol=0.
    for n,pos in enumerate(picks):
        day=days[pos];year=int(day[:4]);hour=(n*7)%24
        t=int(pd.Timestamp(day,tz='UTC').timestamp()*1000)+hour*H
        expected=[]
        for r in daily[daily.day.eq(day)].itertuples(index=False):
            data=by.get((year,r.symbol))
            if data is None:continue
            close_times=np.arange(t-25*H,t,H,dtype=np.int64)
            volume_times=np.array([t-H-k*24*H for k in range(21)],dtype=np.int64)
            z=data.reindex(np.unique(np.r_[close_times,volume_times]))
            if not z.valid.fillna(False).all():continue
            closes=data.reindex(close_times).close.to_numpy(float);ret=np.diff(np.log(closes));sd=ret.std(ddof=1)
            vol=data.reindex(volume_times).quote_volume.to_numpy(float);med=np.median(vol[1:])
            if sd<=0 or med<=0:continue
            score=float(ret[-6:].sum()/sd);rvol=float(vol[0]/med);indicators+=1
            if rvol>=1.5 and score!=0:expected.append({'symbol':r.symbol,'side':1 if score>0 else -1,
                                                        'daily_rank':int(r.rank),'score':score,'rvol':rvol})
        actual=top[top.decision_hour.eq(t)]
        for side in (-1,1):
            x=sorted((e for e in expected if e['side']==side),key=lambda e:(-abs(e['score']),e['daily_rank'],e['symbol']))[:3]
            y=actual[actual.side.eq(side)].sort_values('hourly_rank')
            assert [e['symbol'] for e in x]==y.symbol.tolist(),('ranking mismatch',day,hour,side)
            for a,b in zip(x,y.itertuples(index=False)):
                es=abs(a['score']-float(b.score));ev=abs(a['rvol']-float(b.rvol))
                max_score=max(max_score,es);max_rvol=max(max_rvol,ev)
                assert np.isclose(a['score'],b.score,rtol=1e-8,atol=1e-8)
                assert np.isclose(a['rvol'],b.rvol,rtol=1e-8,atol=1e-8)
        checked+=1
    out={'sampled_decision_hours':checked,'manually_recomputed_candidate_indicators':indicators,
         'max_score_absolute_error':max_score,'max_rvol_absolute_error':max_rvol,
         'current_hour_only_uses_closed_hour_bars':True,'daily_candidate_set_enforced':True,
         'note':'Recomputes from hourly archives; strict constituent-minute completeness remains a separate requirement.'}
    (HERE/'小时排名独立抽样核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE31_RANK_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
