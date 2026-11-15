"""Sample official hourly-feature ranks against independently aggregated minute data."""
import gc,json
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;H=3_600_000;M=60_000
def main():
    top=pd.read_parquet(HERE/'历史动态池小时动量前三_待分钟核验.parquet')
    symbols=['BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT']
    checks=[]
    for year in (2024,2026):
      folder=ROOT/'work'/('breakout_2024_expanded18' if year==2024 else 'breakout_november_2026')/'normalized'
      for symbol in symbols:
        picks=top[(top.year.eq(year))&top.symbol.eq(symbol)].sort_values('decision_hour')
        if not len(picks):continue
        # Pre-set earliest/middle/latest, never choose by favorable agreement.
        positions=sorted(set([0,len(picks)//2,len(picks)-1]));chosen=picks.iloc[positions]
        a=pd.read_parquet(folder/f'{symbol}_klines.parquet')
        assert not a.ts.duplicated().any(),(year,symbol,'duplicate_minutes')
        cols=['open','high','low','close','volume','quote_volume']
        valid=np.isfinite(a[cols].to_numpy(float)).all(axis=1)&(a[cols].to_numpy(float)>0).all(axis=1)
        valid&=(a.high>=a[['open','low','close']].max(axis=1))&(a.low<=a[['open','high','close']].min(axis=1))
        a['ok']=valid;a['hour']=a.ts//H*H
        hours=a.sort_values('ts').groupby('hour').agg(n=('ts','size'),first=('ts','first'),last=('ts','last'),
                   ok=('ok','all'),close=('close','last'),quote=('quote_volume','sum'))
        hours['ok']=hours.ok&(hours.n==60)&(hours.first==hours.index)&(hours.last==hours.index+59*M)
        for r in chosen.itertuples(index=False):
            now=int(r.decision_hour);close_times=np.arange(now-25*H,now,H,dtype=np.int64)
            # Decision uses the bar opened T-1h and previous 20 same-clock bars.
            volume_times=np.array([now-H-k*24*H for k in range(0,21)],dtype=np.int64)
            needed=np.unique(np.r_[close_times,volume_times]);q=hours.reindex(needed)
            if not q.ok.fillna(False).all():
                checks.append({'year':year,'symbol':symbol,'decision_hour':now,'status':'minute_incomplete'});continue
            closes=hours.reindex(close_times).close.to_numpy(float);returns=np.diff(np.log(closes))
            score=float(returns[-6:].sum()/returns.std(ddof=1))
            volumes=hours.reindex(volume_times).quote.to_numpy(float);rvol=float(volumes[0]/np.median(volumes[1:]))
            score_error=abs(score-float(r.score));rvol_error=abs(rvol-float(r.rvol))
            ok=np.isclose(score,float(r.score),rtol=1e-6,atol=1e-7) and np.isclose(rvol,float(r.rvol),rtol=1e-6,atol=1e-7)
            checks.append({'year':year,'symbol':symbol,'decision_hour':now,'status':'verified' if ok else 'feature_mismatch',
                           'score_abs_error':score_error,'rvol_abs_error':rvol_error})
        del a,hours;gc.collect()
    status=pd.Series([x['status'] for x in checks]).value_counts().to_dict()
    out={'samples':checks,'status_counts':status,'checked_symbols':symbols,
         'note':'Only sampled old-pool contracts are checked; new contracts and all feature dependencies still require minute-level validation.'}
    (HERE/'小时特征分钟抽样核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE31_MINUTE_SAMPLE',json.dumps(status,ensure_ascii=False),flush=True)
    if status.get('feature_mismatch',0):raise ValueError('hourly_and_minute_feature_mismatch')
if __name__=='__main__':main()
