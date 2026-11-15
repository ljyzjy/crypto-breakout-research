"""Independently rebuild sampled 30-day and completed-hour cross-sectional ranks."""
import json,math
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;NORM=ROOT/'work'/'breakout_2023_11'/'normalized';M=60_000;HOUR=60*M;DAY=24*HOUR
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
def main():
    daily=pd.read_parquet(H/'固定十一币历史日排名.parquet');top=pd.read_parquet(H/'固定十一币已知小时排名.parquet')
    days=sorted(daily.day.unique());hours=sorted(map(int,top.decision_hour.unique()))
    sampled_days={days[int(i)] for i in np.linspace(0,len(days)-1,12,dtype=int)}
    sampled_hours=[hours[int(i)] for i in np.linspace(0,len(hours)-1,24,dtype=int)]
    sampled_days.update(pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d') for t in sampled_hours)
    daily_input={};hour_input={}
    for sym in SYMBOLS:
        d=pd.read_parquet(NORM/f'{sym}_klines.parquet').sort_values('ts');assert not d.ts.duplicated().any() and (d.ts%M==0).all()
        x=d[['open','high','low','close','volume','quote_volume','trade_count']].to_numpy(float);o,h,l,c,v,q,n=x.T
        struct=np.isfinite(x).all(axis=1)&(x[:,:4]>0).all(axis=1)&(x[:,4:]>=0).all(axis=1)
        good=np.isfinite(x[:,:6]).all(axis=1)&(x[:,:6]>0).all(axis=1)&(h>=np.maximum.reduce([o,l,c]))&(l<=np.minimum.reduce([o,h,c]))
        d=d.assign(daykey=d.ts//DAY,hourkey=d.ts//HOUR,struct=struct,good=good)
        ds=d.groupby('daykey',sort=True).agg(n=('ts','size'),valid=('struct','sum'),quote=('quote_volume','sum'))
        ds.loc[(ds.n!=1440)|(ds.valid!=1440)|(ds.quote<=0),'quote']=np.nan
        hs=d.groupby('hourkey',sort=True).agg(n=('ts','size'),valid=('good','sum'),close=('close','last'),quote=('quote_volume','sum'))
        hs.loc[(hs.n!=60)|(hs.valid!=60),['close','quote']]=np.nan
        daily_input[sym]=ds;hour_input[sym]=hs
    ranks={}
    for date in sorted(sampled_days):
        t=int(pd.Timestamp(date,tz='UTC').timestamp()*1000)//DAY;values=[]
        for sym in SYMBOLS:
            g=daily_input[sym].reindex(range(t-30,t));v=g.quote.to_numpy(float)
            assert len(v)==30 and np.isfinite(v).all() and (v>0).all(),(date,sym)
            values.append((sym,float(v.sum())))
        expected=sorted(values,key=lambda x:(-x[1],x[0]));got=daily[daily.day.eq(date)].sort_values('liquidity_rank')
        assert list(got.symbol)==[x[0] for x in expected]
        assert np.allclose(got.past_30d_quote.to_numpy(float),[x[1] for x in expected],rtol=1e-10,atol=1e-6)
        ranks[date]={sym:i+1 for i,(sym,_) in enumerate(expected)}
    for t in sampled_hours:
        date=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d');cur=t//HOUR-1;pred=[]
        for sym in SYMBOLS:
            hs=hour_input[sym];prices=hs.reindex(range(cur-24,cur+1)).close.to_numpy(float)
            quote=float(hs.reindex([cur]).quote.iloc[0]);past=hs.reindex([cur-24*i for i in range(1,21)]).quote.to_numpy(float)
            assert np.isfinite(prices).all() and np.isfinite(quote) and np.isfinite(past).all() and (prices>0).all() and (past>0).all()
            returns=np.diff(np.log(prices));vol=float(np.std(returns,ddof=1));assert vol>0
            score=float(returns[-6:].sum()/vol);rvol=float(quote/np.median(past))
            if rvol>=1.5 and score!=0:pred.append({'symbol':sym,'side':1 if score>0 else -1,'score':score,'rvol':rvol,'liquidity_rank':ranks[date][sym]})
        expected=[]
        for side in (-1,1):
            x=sorted((v for v in pred if v['side']==side),key=lambda v:(-abs(v['score']),v['liquidity_rank'],v['symbol']))
            for i,v in enumerate(x[:3],1):expected.append({**v,'hourly_rank':i})
        got=top[top.decision_hour.eq(t)]
        assert len(got)==len(expected)
        for x in expected:
            row=got[(got.symbol==x['symbol'])&(got.side==x['side'])];assert len(row)==1;z=row.iloc[0]
            assert int(z.hourly_rank)==x['hourly_rank'] and int(z.liquidity_rank)==x['liquidity_rank']
            assert math.isclose(float(z.score),x['score'],rel_tol=1e-9,abs_tol=1e-10)
            assert math.isclose(float(z.rvol),x['rvol'],rel_tol=1e-9,abs_tol=1e-10)
    out={'daily_rank_days_recomputed':len(sampled_days),'hourly_rank_times_recomputed':len(sampled_hours),
         'symbols_per_hour':len(SYMBOLS),'all_checks_pass':True,
         'note':'Samples only; the fixed 11-coin universe has survivorship bias.'}
    (H/'2023日小时排名独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_RANK_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
