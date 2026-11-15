"""Fixed exploratory factor tests. Future labels never enter strategy features."""
import numpy as np
import pandas as pd
from st_engine import ROOT,SYMBOLS,inputs,dump

FACTORS=('M24','BR24','RVOL','TBI4','D24','NATR14')
LABELS={'M24':'24 小时动量','BR24':'突破强度','RVOL':'相对成交额','TBI4':'主动成交不平衡','D24':'VWAP 偏离','NATR14':'相对波动'}


def rank_ic(frame):
    if len(frame)<20 or frame.x.nunique()<2 or frame.y.nunique()<2:return None
    return float(frame.x.rank().corr(frame.y.rank()))


def inference(frame):
    # Rank within each coin, then pool. For a single coin this is Spearman IC.
    a=frame.copy();a['xr']=a.groupby('symbol').x.rank(pct=True);a['yr']=a.groupby('symbol').y.rank(pct=True)
    x=a.xr.to_numpy();y=a.yr.to_numpy();ic=float(np.corrcoef(x,y)[0,1])
    blocks=(a['ts']//(7*86400)).to_numpy()
    unique,inverse=np.unique(blocks,return_inverse=True)
    stats=np.zeros((len(unique),6));values=np.column_stack([np.ones(len(x)),x,y,x*x,y*y,x*y])
    np.add.at(stats,inverse,values)
    rng=np.random.default_rng(20261112);samples=stats[rng.integers(0,len(stats),size=(499,len(stats)))].sum(axis=1)
    n,sx,sy,sxx,syy,sxy=samples.T
    boots=(sxy-sx*sy/n)/np.sqrt((sxx-sx*sx/n)*(syy-sy*sy/n))
    boots=boots[np.isfinite(boots)]
    ci=np.quantile(boots,[.025,.975]);p=(1+int((np.abs(boots-ic)>=abs(ic)).sum()))/(len(boots)+1)
    return {'ic':ic,'ci_low':float(ci[0]),'ci_high':float(ci[1]),'p_approx':p,'blocks':len(unique)}


def run():
    data,fs=inputs();rows=[];thresholds={}
    for factor in FACTORS:
        for h in (4,24):
            chunks=[]
            for symbol in SYMBOLS:
                raw=data[(symbol,'1h')].reindex(fs[symbol].index)
                entry=raw.open.shift(-1);exit=raw.open.shift(-1-h)
                y=(exit*.9995*.999)/(entry*1.0005*1.001)-1
                complete=(raw.open.notna()&raw.volume.gt(0)).rolling(h+1).sum().shift(-h-1).eq(h+1)
                stamp=raw.index+pd.Timedelta(hours=1);exit_stamp=stamp+pd.Timedelta(hours=h)
                a=pd.DataFrame({'x':fs[symbol][factor].to_numpy(),'y':y.where(complete).to_numpy(),'symbol':symbol,
                                'ts':stamp.as_unit('s').asi8,'stamp':stamp,'exit_stamp':exit_stamp}).dropna(subset=['x','y'])
                train=a[(a.stamp>=pd.Timestamp('2023-01-01',tz='UTC'))&(a.exit_stamp<pd.Timestamp('2024-01-01',tz='UTC'))]
                levels=train.x.quantile([1/3,2/3]).to_numpy();thresholds[f'{factor}_{h}_{symbol}']=levels.tolist()
                test=a[(a.stamp>=pd.Timestamp('2024-01-01',tz='UTC'))&(a.exit_stamp<pd.Timestamp('2026-11-01',tz='UTC'))].copy()
                test['bucket']=np.searchsorted(levels,test.x,side='right')
                chunks.append(test)
            combined=pd.concat(chunks,ignore_index=True)
            for scope in ('pooled',*SYMBOLS):
                a=combined if scope=='pooled' else combined[combined.symbol==scope]
                stats=inference(a)
                non=a[(a.ts//3600)%h==0]
                # The pooled non-overlapping statistic also ranks within each coin.
                x=non.groupby('symbol').x.rank(pct=True);y=non.groupby('symbol').y.rank(pct=True)
                group=[{'bucket':i,'count':int((a.bucket==i).sum()),'mean_net_bps':float(a.loc[a.bucket==i,'y'].mean()*10000)} for i in range(3)]
                rows.append({'factor':factor,'name':LABELS[factor],'horizon':h,'scope':scope,'count':len(a),
                             **stats,'nonoverlap_count':len(non),'nonoverlap_ic':float(x.corr(y)),
                             'groups':group,'high_minus_low_bps':group[2]['mean_net_bps']-group[0]['mean_net_bps']})
    order=np.argsort([r['p_approx'] for r in rows]);m=len(rows);running=1.
    for j in range(m-1,-1,-1):
        i=int(order[j]);running=min(running,rows[i]['p_approx']*m/(j+1));rows[i]['q_bh']=float(running)
    result={'training':'2023; labels ending before 2024','evaluation':'2024-01-01 to 2026-10-31',
            'status':'exploratory, already-seen history; not an investable portfolio',
            'method':'Within-coin ranks, paired UTC seven-day fixed-rank block bootstrap (499, seed 20261112); approximate centered p; BH across all 36 tests.',
            'cost':'each side fee .1% plus slippage .05%; next executable open labels',
            'interpretation':'IC direction does not establish profitability. Conditional volume/deviation factors and volatility risk tools may be nonlinear. Bucket returns overlap and cannot be summed into account returns.',
            'thresholds':thresholds,'rows':rows}
    dump(ROOT/'factors.json',result)
    pd.json_normalize(rows).drop(columns=['groups']).to_csv(ROOT/'factor_metrics.csv',index=False,encoding='utf-8-sig')
    return result


if __name__=='__main__':
    result=run();print('Factor tests complete:',len(result['rows']))
