"""Frozen, chronological group increment methods. Import does not load real outcomes."""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd

MINUTE = 60000
DAY = 86400000
GROUPS = {
 'F1': ['signed_residual6'],
 'F2': ['efficiency6','concentration6'],
 'F3': ['rv_relative60','range_atr'],
 'F4': ['boundary_distance','outside_fraction5'],
 'F5': ['drawdown_atr','recovery_fraction'],
 'F6': ['log_count_rvol'],
}
BASE = ['signed_r6','signed_btc_r6','vol24','log_quote_rvol','utc_hour_sin','utc_hour_cos']

def sha_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(2**20),b''): h.update(b)
    return h.hexdigest()

def id_hash(ids):
    return hashlib.sha256('\n'.join(sorted(map(str,ids))).encode()).hexdigest()

def design_values(frame):
    d=frame.copy()
    d['signed_r6']=d.side*d.r6
    d['signed_btc_r6']=d.side*d.btc_r6
    d['signed_residual6']=d.side*d.residual6
    d['log_quote_rvol']=np.log1p(d.quote_rvol)
    d['log_count_rvol']=np.log1p(d.count_rvol)
    return d

def fit_ols(frame, target, columns, metadata=None):
    """Only supplied training data sets scales, coefficients and reference coin."""
    d=design_values(frame)
    y=np.asarray(target,dtype=float)
    if not len(d) or not np.isfinite(y).all(): raise ValueError('Empty/nonfinite target')
    scaler={}; active=[]; constants=[]
    for c in columns:
        v=d[c].to_numpy(float)
        if not np.isfinite(v).all(): raise ValueError('Nonfinite training design: '+c)
        med=float(np.median(v)); iqr=float(np.quantile(v,.75)-np.quantile(v,.25))
        constant=bool(np.all(v==v[0]))
        scaler[c]={'median':med,'scale':iqr if iqr>0 else 1.,'iqr':iqr,'constant':constant,'iqr_zero_nonconstant':iqr==0 and not constant}
        (constants if constant else active).append(c)
    coins=sorted(d.symbol.astype(str).unique())
    model={'input_columns':columns,'active_columns':active,'constant_columns':constants,'scaler':scaler,
           'coin_levels':coins,'reference_coin':coins[0],'rcond':1e-12,'metadata':metadata or {}}
    x=matrix(d,model)
    coef,_,rank,s=np.linalg.lstsq(x,y,rcond=1e-12)
    model.update(coef=coef.tolist(),rank=int(rank),n_rows=len(d),n_columns=x.shape[1],singular_values=s.tolist(),
                 matrix_columns=['intercept']+active+['coin:'+c for c in coins[1:]])
    return model

def matrix(d,model):
    cols=[np.ones(len(d))]
    for c in model['active_columns']:
        z=model['scaler'][c]
        cols.append((d[c].to_numpy(float)-z['median'])/z['scale'])
    sy=d.symbol.astype(str).to_numpy()
    cols.extend((sy==c).astype(float) for c in model['coin_levels'][1:])
    return np.column_stack(cols)

def predict_ols(frame,model):
    d=design_values(frame)
    # Even a constant training variable needs to exist at decision time.
    valid=np.isfinite(d[model['input_columns']].to_numpy(float)).all(axis=1)
    out=np.full(len(d),np.nan)
    out[valid]=matrix(d.loc[valid],model)@np.asarray(model['coef'])
    return out,valid,~d.symbol.astype(str).isin(model['coin_levels']).to_numpy()

def sample_stats(frame):
    dt=pd.to_datetime(frame.decision_ts,unit='ms',utc=True)
    weeks=dt.dt.strftime('%G-%V')
    result={'records':len(frame),'active_days':int(dt.dt.floor('D').nunique()),
            'active_weeks':int(weeks.nunique()),'coins':int(frame.symbol.nunique()),
            'id_sha256':id_hash(frame.observation_id)}
    result['minimum_pass']=result['records']>=200 and result['active_days']>=30 and result['active_weeks']>=8 and result['coins']>=5
    return result

def daily_loss(frame,y,base,enh,start_ms,end_ms):
    d=pd.DataFrame({'day':frame.decision_ts.to_numpy()//DAY,'symbol':frame.symbol.to_numpy(),
                    'loss_base':(np.asarray(y)-base)**2,'loss_enhanced':(np.asarray(y)-enh)**2})
    d=d.groupby(['day','symbol'],observed=True)[['loss_base','loss_enhanced']].mean().groupby('day').mean()
    axis=np.arange(start_ms//DAY,end_ms//DAY)
    d=d.reindex(axis); d['difference']=d.loss_base-d.loss_enhanced
    return d

def block_test(daily_difference,reps=2000,seed=20261113,block=7):
    """Moving blocks on calendar axis; NA days retained, all coins synchronous."""
    a=np.asarray(daily_difference,dtype=float); n=len(a)
    if n<block or not np.isfinite(a).any():
        return {'mean_difference':None,'p_raw':1.,'ci95':[None,None],'bootstrap_valid':0}
    observed=float(np.nanmean(a)); centered=a-observed
    rng=np.random.default_rng(seed)
    draws=[]; nul=[]
    for _ in range(reps):
        starts=rng.integers(0,n-block+1,size=int(np.ceil(n/block)))
        ix=(starts[:,None]+np.arange(block)).ravel()[:n]
        if np.isfinite(a[ix]).any():
            draws.append(float(np.nanmean(a[ix]))); nul.append(float(np.nanmean(centered[ix])))
    if len(draws)!=reps: raise ValueError('Bootstrap encountered all-missing draw')
    return {'mean_difference':observed,'p_raw':float((1+np.count_nonzero(np.asarray(nul)>=observed))/(reps+1)),
            'ci95':np.quantile(draws,[.025,.975]).tolist(),'bootstrap_valid':len(draws),'block_days':block,'seed':seed}

def holm(pvalues):
    keys=list(pvalues); order=sorted(keys,key=lambda k:(pvalues[k],k)); out={}; prev=0.
    for i,k in enumerate(order):
        prev=max(prev,min(1.,(len(keys)-i)*pvalues[k])); out[k]=prev
    return out

def temporal_mask(frame,start_ms,end_ms,horizon=60,purge_minutes=65):
    return (frame.decision_ts.ge(start_ms)&frame.decision_ts.lt(end_ms-purge_minutes*MINUTE)&
            (frame.decision_ts+(1+horizon)*MINUTE).lt(end_ms))

def make_labels(opportunities,minutes,horizons=(15,30,60)):
    """Ex-post labels only. No label-validity value is used for entry availability.

    Entry = decision+1m open. Full positive-volume OHLC path [entry,exit),
    but exit requires only finite positive open, which exists at exit time.
    Direction log-return and nonnegative MFE/MAE are in basis points.
    """
    out=opportunities[['observation_id','symbol','contract','decision_ts','side']].copy().reset_index(drop=True)
    out['entry_ts']=out.decision_ts+MINUTE
    if minutes.empty:
        for h in horizons:
            out[f'exit_ts_{h}']=out.entry_ts+h*MINUTE
            out[f'label_valid_{h}']=False
            out[f'label_reason_{h}']='missing_market'
            for c in ['gross_bp','net20bp_proxy','mfe_bp','mae_bp']:out[f'{c}_{h}']=np.nan
        return out
    d=minutes.sort_values('ts').set_index('ts')
    if d.index.has_duplicates: raise ValueError('Duplicate minute timestamps')
    lo=min(int(out.entry_ts.min()),int(d.index.min()))
    hi=max(int(out.entry_ts.max())+max(horizons)*MINUTE,int(d.index.max()))
    axis=np.arange(lo,hi+MINUTE,MINUTE,dtype='int64')
    d=d.reindex(axis)
    ohlc=d[['open','high','low','close']].to_numpy(float)
    valid=np.isfinite(ohlc).all(axis=1)&(ohlc>0).all(axis=1)
    valid &= (d.high>=d[['open','close','low']].max(axis=1)).to_numpy()&(d.low<=d[['open','close','high']].min(axis=1)).to_numpy()
    valid &= d.volume.gt(0).to_numpy()&d.quote_volume.gt(0).to_numpy()
    bad_prefix=np.r_[0,np.cumsum(~valid)]
    entry=((out.entry_ts.to_numpy()-lo)//MINUTE).astype(int)
    prices=d.open.to_numpy(float); ep=prices[entry]; side=out.side.to_numpy(float)
    for h in horizons:
        end=entry+h; xp=prices[end]
        pathgood=(bad_prefix[end]-bad_prefix[entry])==0
        exitgood=np.isfinite(xp)&(xp>0)
        direction=np.isin(side,[-1,1])
        ok=pathgood&exitgood&direction
        high=d.high.rolling(h,min_periods=h).max().to_numpy()[end-1]
        low=d.low.rolling(h,min_periods=h).min().to_numpy()[end-1]
        with np.errstate(invalid='ignore',divide='ignore'):
            gross=side*np.log(xp/ep)*10000
            mfe=np.maximum(0.,np.where(side>0,np.log(high/ep),np.log(ep/low))*10000)
            mae=np.maximum(0.,np.where(side>0,np.log(ep/low),np.log(high/ep))*10000)
        reason=np.where(~direction,'missing_direction',np.where(~pathgood,'missing_or_invalid_held_minute',np.where(~exitgood,'missing_exit_open','valid')))
        out[f'exit_ts_{h}']=out.entry_ts+h*MINUTE
        out[f'label_valid_{h}']=ok; out[f'label_reason_{h}']=reason
        out[f'gross_bp_{h}']=np.where(ok,gross,np.nan)
        out[f'net20bp_proxy_{h}']=np.where(ok,gross-20.,np.nan)
        out[f'mfe_bp_{h}']=np.where(ok,mfe,np.nan)
        out[f'mae_bp_{h}']=np.where(ok,mae,np.nan)
    return out
