"""Accounting adapter for the frozen Phase 3 market and causal pool/correlation."""
import numpy as np
import pandas as pd
from pathlib import Path
from market_io import (get_manifest, load_minutes, load_mark, load_funding,
                       load_daily_pools, load_mapping, PHASE2)

MINUTE=60_000
ROOT=Path(__file__).resolve().parent


class Market:
    def __init__(self):
        self.manifest=get_manifest()
        self.month=None
        self.px={}; self.mark={}; self.funding={}; self.bounds={}
        self.month_contracts={}
        for r in self.manifest['records']:
            self.month_contracts.setdefault(r['month'],set()).add(r['contract'])

    def change_month(self,ts):
        month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
        if month==self.month:return
        self.month=month; self.px={}; self.mark={}; self.funding={}; self.bounds={}
        start=pd.Timestamp(month+'-01',tz='UTC'); end=start+pd.offsets.MonthBegin(1)
        self.base=int(start.timestamp()*1000)
        end_ms=int(end.timestamp()*1000)
        self.count=int((end-start).total_seconds()/60)
        ix=np.arange(self.base,end_ms,MINUTE,dtype='int64')
        for c in sorted(self.month_contracts.get(month,set())):
            for loader,target,columns in (
                (load_minutes,self.px,['open','high','low','close','volume','quote_volume']),
                (load_mark,self.mark,['open','high','low','close'])):
                d=loader(c,self.base,end_ms)
                if len(d):target[c]=d.set_index('ts').reindex(ix)[columns].to_numpy(float)
            d=load_funding(c,self.base,end_ms)
            if len(d):
                events={}
                for row in d.itertuples(index=False):
                    events.setdefault(int(row.ts)//MINUTE*MINUTE,[]).append((int(row.ts),float(row.last_funding_rate)))
                self.funding[c]=events
                self.bounds[c]=d[['ts','funding_interval_hours']].to_numpy(float)

    def bar(self,c,ts,mark=False):
        data=(self.mark if mark else self.px).get(c)
        i=(ts-self.base)//MINUTE
        if data is None or i<0 or i>=self.count:return None
        x=data[i]
        return x if np.isfinite(x[:4]).all() else None

    def funding_ok(self,c,ts):
        if c not in self.funding:return False
        rows=self.bounds[c]
        if len(rows)<1:return False
        pos=np.searchsorted(rows[:,0],ts,side='right')
        before=rows[max(0,pos-1)]; after=rows[min(len(rows)-1,pos)]
        allowance=max(before[1],after[1])*3_600_000*1.5
        if pos==0:return rows[0,0]-ts<=allowance
        if pos==len(rows):return ts-rows[-1,0]<=allowance
        return after[0]-before[0]<=allowance


class PoolCorrelationGuard:
    """Current known daily pool and original 72-complete-hour correlation cap.

    Signal formation is supplied by the frozen candidate adapter. This guard
    does not silently reintroduce old RVOL/rank/trend entry rules.
    """
    def __init__(self):
        self.pools={int(pd.Timestamp(r['date'],tz='UTC').timestamp()*1000):
                    {x['symbol'] for x in r['pool']} for r in load_daily_pools()}
        hourly=[]
        for symbol,contract in load_mapping().items():
            if not contract:continue
            p=PHASE2/'feature_outputs/hourly'/f'{contract}.parquet'
            if not p.exists():continue
            d=pd.read_parquet(p,columns=['ts','hourly_return'])
            d['symbol']=symbol;hourly.append(d)
        self.h=pd.concat(hourly).pivot(index='ts',columns='symbol',values='hourly_return').sort_index()
        self.cache={}

    def eligible(self,s,side,ts):
        return s in self.pools.get(ts//86_400_000*86_400_000,set())

    def correlation(self,a,sa,b,sb,ts):
        hour=ts//3_600_000*3_600_000; key=(hour,a,b)
        if key not in self.cache:
            if a not in self.h or b not in self.h:
                self.cache[key]=None
            else:
                ix=np.arange(hour-71*3_600_000,hour+1,3_600_000,dtype='int64')
                d=self.h.reindex(ix)[[a,b]]
                self.cache[key]=float(d[a].corr(d[b])) if d.notna().all().all() and d.std().gt(0).all() else None
        rho=self.cache[key]
        return None if rho is None else sa*sb*rho


class RankTrendGuard(PoolCorrelationGuard):
    def __init__(self):
        super().__init__()
        ranks=pd.read_parquet(ROOT/'hourly-ranks.parquet')
        self.ranks={(int(r.hour),r.symbol,int(r.side)) for r in ranks.itertuples()}
        q=pd.read_parquet(ROOT/'regimes.parquet')
        self.q={s:g.sort_values('ts')[['ts','direction']].to_numpy() for s,g in q.groupby('symbol')}

    def eligible(self,s,side,ts):
        if not super().eligible(s,side,ts):return False
        if (ts//3_600_000*3_600_000,s,side) not in self.ranks:return False
        if s not in self.q:return False
        q=self.q[s];i=np.searchsorted(q[:,0],ts,side='right')-1
        return i>=0 and ts-q[i,0]<900_000 and q[i,1]==side


def build_guards():
    """Deterministic known-at-time features only, no return/label access."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('phase2_feature_data_io',PHASE2/'data_io.py')
    phase2_data=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(phase2_data)
    pools=[]
    for day in load_daily_pools():
        base=int(pd.Timestamp(day['date'],tz='UTC').timestamp()*1000)
        for rank,item in enumerate(day['pool'],1):
            pools.append({'day':base,'symbol':item['symbol'],'liquidity_rank':rank})
    pools=pd.DataFrame(pools)
    frames=[]; quarters=[]
    for symbol,contract in load_mapping().items():
        if not contract:continue
        source=PHASE2/'feature_outputs/hourly'/f'{contract}.parquet'
        if not source.exists():continue
        h=pd.read_parquet(source,columns=['ts','r6','vol24','quote_rvol'])
        h['symbol']=symbol;h['contract']=contract
        h['score']=h.r6/h.vol24.where(h.vol24.gt(0))
        h['day']=h.ts//86_400_000*86_400_000
        frames.append(h)
        # Supplemental exit-month trade archives are accounting-only; the EMA
        # uses exactly the original normalized Phase 2 feature input version.
        raw=phase2_data.load_minutes(contract)
        raw.index=pd.to_datetime(raw.ts,unit='ms',utc=True)
        raw=raw.reindex(pd.date_range(raw.index.min(),raw.index.max(),freq='min'))
        vals=raw[['open','high','low','close','volume','quote_volume']]
        ok=np.isfinite(vals).all(axis=1)&vals.gt(0).all(axis=1)
        ok &= raw.high.ge(raw[['open','close','low']].max(axis=1))&raw.low.le(raw[['open','close','high']].min(axis=1))
        q=raw.close.where(ok).resample('15min',label='right',closed='left').last()
        good=ok.resample('15min',label='right',closed='left').sum().eq(15)
        q=q.where(good)
        ema=q.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
        direction=np.select([q.gt(ema)&ema.gt(ema.shift()),q.lt(ema)&ema.lt(ema.shift())],[1,-1],0)
        z=pd.DataFrame({'ts':q.index.as_unit('ms').asi8,'symbol':symbol,'direction':direction})
        z=z[z.ts.le(int(raw.index.max().timestamp()*1000)+MINUTE)]
        quarters.append(z)
    h=pd.concat(frames,ignore_index=True).merge(pools,on=['day','symbol'],how='inner')
    h=h[h.quote_rvol.ge(1.5)&h.score.notna()&h.score.ne(0)].copy()
    h['side']=np.sign(h.score).astype(int);h['strength']=h.score.abs()
    h=h.sort_values(['ts','side','strength','liquidity_rank','symbol'],ascending=[True,True,False,True,True])
    h=h.groupby(['ts','side'],sort=False).head(3).copy()
    h['rank']=h.groupby(['ts','side']).cumcount()+1
    h=h.rename(columns={'ts':'hour','quote_rvol':'rvol'})
    h[['hour','symbol','contract','side','score','rank','rvol','liquidity_rank']].to_parquet(ROOT/'hourly-ranks.parquet',index=False)
    pd.concat(quarters,ignore_index=True).to_parquet(ROOT/'regimes.parquet',index=False)
    return {'rank_rows':len(h),'regime_rows':sum(len(q) for q in quarters),'outcomes_computed':False}
