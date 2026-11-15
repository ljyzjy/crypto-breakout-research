"""Fixed30min signal markout, all events including post-pause; not account P&L."""
from common import ROOT,SOURCE,read,dump,load_contract
import numpy as np
import pandas as pd
M=60000
def main():
    spec=read(ROOT/'protocol.json');base=ROOT.parent/'pullback-intraday-no-daily-cap-v1'
    folders={'baseline':base,**{k:ROOT/'runs'/k for k in spec['versions']}}
    signals={k:pd.read_parquet(p/'signals.parquet') for k,p in folders.items()}
    stop=int((pd.Timestamp(spec['end'],tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    rows=[]
    contracts=sorted(set().union(*(set(s.contract) for s in signals.values())))
    for contract in contracts:
        raw=load_contract(contract,'klines');ix=pd.date_range(raw.index.min(),raw.index.max(),freq='min');raw=raw.reindex(ix)
        times=ix.as_unit('ms').asi8;op=raw.open.to_numpy();valid=(raw[['open','high','low','close']].gt(0).all(axis=1)&raw.volume.gt(0)).to_numpy()
        count=np.r_[0,np.cumsum(~valid)]
        for key,s in signals.items():
            a=s[s.contract.eq(contract)];ts=a.ts.to_numpy(dtype='int64');j=(ts-times[0])//M;k=j+30
            use=(j>=0)&(k<len(raw))&(ts+30*M<stop)
            z=np.flatnonzero(use);z=z[(count[k[z]+1]-count[j[z]])==0]
            for pos in z:
                r=a.iloc[pos];bp=float(r.side*(op[k[pos]]/op[j[pos]]-1)*1e4)
                rows.append({'variant':key,'ts':int(r.ts),'symbol':r.symbol,'side':int(r.side),'gross_bps':bp,'after_20bps_proxy':bp-20})
    frame=pd.DataFrame(rows);frame.to_parquet(ROOT/'signal-markouts.parquet',index=False)
    summaries=[]
    for key,g in frame.groupby('variant'):
        g=g.sort_values(['symbol','ts']);keep=[];next_ts={}
        for r in g.itertuples():
            if r.ts>=next_ts.get(r.symbol,0):keep.append(r.gross_bps);next_ts[r.symbol]=r.ts+30*M
        summaries.append({'variant':key,'signals':len(signals[key]),'valid_30m':len(g),'gross_bps':float(g.gross_bps.mean()),'after_20bps_proxy':float(g.after_20bps_proxy.mean()),'nonoverlap_count':len(keep),'nonoverlap_gross_bps':float(np.mean(keep))})
    dump(ROOT/'signal-diagnostics.json',{'horizon_minutes':30,'roundtrip_proxy_bps':20,'funding_included':False,'portfolio_constraints_applied':False,'overlap_is_not_independence':True,'rows':summaries})
    print('DIAGNOSTICS COMPLETE',len(frame))
if __name__=='__main__':main()
