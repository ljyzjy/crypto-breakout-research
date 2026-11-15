from common import ROOT
import numpy as np
import pandas as pd
class Guard:
    def __init__(self):
        ranks=pd.read_parquet(ROOT/'hourly-ranks.parquet')
        self.ranks={(int(r.hour),r.symbol,int(r.side)) for r in ranks.itertuples()}
        q=pd.read_parquet(ROOT/'regimes.parquet');self.q={s:g.sort_values('ts')[['ts','direction']].to_numpy() for s,g in q.groupby('symbol')}
        h=pd.read_parquet(ROOT/'hourly.parquet');h['ret']=h.groupby('symbol').close.transform(lambda x:np.log(x).diff())
        self.h=h.pivot(index='ts',columns='symbol',values='ret').sort_index()
        self.cache={}
    def eligible(self,s,side,ts):
        if (ts//3600000*3600000,s,side) not in self.ranks:return False
        q=self.q[s];i=np.searchsorted(q[:,0],ts,side='right')-1
        return i>=0 and ts-q[i,0]<900000 and q[i,1]==side
    def correlation(self,a,sa,b,sb,ts):
        hour=ts//3600000*3600000;key=(hour,a,b)
        if key not in self.cache:
            d=self.h.loc[hour-71*3600000:hour,[a,b]]
            self.cache[key]=float(d[a].corr(d[b])) if len(d)==72 and d.notna().all().all() and d.std().gt(0).all() else None
        rho=self.cache[key]
        return None if rho is None else sa*sb*rho
