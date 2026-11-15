"""Registered causal factors and entry stages. No outcome-based fitting."""
from common import ROOT,SOURCE,read,dump,sha,load_contract
from baseline_features import frame
import zipfile, gc, shutil
import numpy as np
import pandas as pd
M=60000;H=3600000
BASE=ROOT.parent/'pullback-intraday-no-daily-cap-v1'
SIGNAL_COLS=['ts','symbol','contract','side','signal_close','atr','stop_price','level','break_ts','accept_ts','touch_ts','previous_quote_volume','hour','score','rank','rvol']

def historical_median(series,spacing):
    history=pd.concat([series.shift(spacing*k) for k in range(1,21)],axis=1)
    return history.median(axis=1).where(history.notna().all(axis=1)&history.gt(0).all(axis=1))

def load_extended(contract,manifest=None):
    """Read original archives, prove identity with frozen trade-price cache."""
    raw=load_contract(contract,'klines')
    if raw.empty:return raw,[]
    manifest=manifest or read(SOURCE/'data-manifest.json')
    chunks=[];audit=[]
    for rec in manifest['records']:
        if rec['contract']!=contract or rec['kind']!='klines':continue
        path=SOURCE/'archives/klines'/rec['key'].split('/')[-1]
        assert sha(path)==rec['archive_sha256'],path
        with zipfile.ZipFile(path) as z:
            d=pd.read_csv(z.open(z.namelist()[0]),usecols=['open_time','volume','quote_volume','count','taker_buy_quote_volume'])
        d=d.rename(columns={'open_time':'ts'});d['ts']=pd.to_numeric(d.ts).astype('int64')
        for c in ['volume','quote_volume','count','taker_buy_quote_volume']:d[c]=pd.to_numeric(d[c],errors='raise')
        assert np.isfinite(d.to_numpy()).all()
        assert (d['count']>=0).all() and (d['count']%1==0).all()
        assert (d.taker_buy_quote_volume>=0).all()
        assert (d.taker_buy_quote_volume<=d.quote_volume*(1+1e-9)+1e-7).all()
        chunks.append(d);audit.append({'archive':path.name,'sha256':rec['archive_sha256'],'rows':len(d)})
    extra=pd.concat(chunks).sort_values('ts').set_index('ts')
    assert not extra.index.duplicated().any()
    assert np.array_equal(extra.index.to_numpy(),raw.ts.to_numpy())
    for c in ['volume','quote_volume']:assert np.allclose(extra[c],raw[c],rtol=1e-10,atol=1e-8)
    raw=raw.copy();raw['count']=extra['count'].to_numpy();raw['taker_buy_quote_volume']=extra.taker_buy_quote_volume.to_numpy()
    return raw,audit

def enrich_hourly(raw,h,btc):
    h=h.copy();r=np.log(h.close).diff();b=np.log(btc.close).diff().reindex(h.index)
    paired=r.notna()&b.notna();x=b.where(paired);y=r.where(paired)
    vb=x.rolling(720,min_periods=720).var(ddof=1).shift(6)
    beta=y.rolling(720,min_periods=720).cov(x).shift(6)/vb.where(vb>1e-16)
    alpha=y.rolling(720,min_periods=720).mean().shift(6)-beta*x.rolling(720,min_periods=720).mean().shift(6)
    r6=r.rolling(6,min_periods=6).sum();b6=b.rolling(6,min_periods=6).sum()
    residual=r6-6*alpha-beta*b6
    # Use the SAME currently known coefficients for all24 residual observations.
    v24=y.rolling(24,min_periods=24).var(ddof=1)+beta**2*x.rolling(24,min_periods=24).var(ddof=1)-2*beta*y.rolling(24,min_periods=24).cov(x)
    h['beta']=beta;h['alpha']=alpha;h['return6']=r6;h['residual6']=residual
    h['residual_score']=residual/np.sqrt(6*v24.where(v24>1e-20))
    denom=r.abs().rolling(6,min_periods=6).sum()
    h['efficiency']=r6.abs()/denom.where(denom>0)
    d=raw.reindex(pd.date_range(raw.index.min(),raw.index.max(),freq='min'))
    ok=d[['open','high','low','close']].gt(0).all(axis=1)&d.volume.gt(0)&d['count'].gt(0)
    a=d[['quote_volume','count','taker_buy_quote_volume']].where(ok)
    hourly=a.resample('1h',label='right',closed='left').sum(min_count=60)
    h['count_rvol']=hourly['count']/historical_median(hourly['count'],24)
    h['taker_imbalance']=(2*hourly.taker_buy_quote_volume-hourly.quote_volume)/hourly.quote_volume
    quarter=a.quote_volume.resample('15min',label='right',closed='left').sum(min_count=15)
    qmedian=historical_median(quarter,96)
    qactive=quarter.ge(qmedian).astype(float).where(quarter.notna()&qmedian.notna())
    h['active_quarters']=qactive.rolling(4,min_periods=4).sum().reindex(h.index)
    h['peak_quarter_share']=(quarter.rolling(4,min_periods=4).max()/quarter.rolling(4,min_periods=4).sum()).reindex(h.index)
    return h.replace([np.inf,-np.inf],np.nan)

def rank_hours(eligible,config):
    g=eligible.copy()
    if config['residual'] or config['matched']:
        g=g[g.residual_score.notna()&g.contract.ne('BTCUSDT')]
    g['score']=g.residual_score if config['residual'] else g.score
    if config['path']:g['score']=g.score*g.efficiency
    g=g[g.rvol.ge(1.5)&g.score.notna()&g.score.ne(0)]
    if config['residual']:g=g[g.score*g.return6>0]
    if config['activity']:g=g[g.count_rvol.ge(1)&g.active_quarters.ge(3)]
    g['side']=np.sign(g.score).astype(int);g['strength']=g.score.abs()
    g=g.sort_values(['ts','side','strength','liquidity_rank','symbol'],ascending=[True,True,False,True,True])
    g=g.groupby(['ts','side'],sort=False).head(3).copy();g['rank']=g.groupby(['ts','side']).cumcount()+1
    cols=['ts','symbol','contract','side','rank','score','rvol','liquidity_rank','beta','alpha','return6','residual6','residual_score','efficiency','count_rvol','active_quarters','taker_imbalance','peak_quarter_share']
    return g[cols].rename(columns={'ts':'hour'}).sort_values(['hour','side','rank']).reset_index(drop=True)

def signals_for(d,ranks,symbol,contract,acceptance=False):
    """Skip inactive hours, but compute break freshness on ALL closed bars."""
    counts={k:0 for k in ['breakouts','accepted','pullbacks','confirmations','expired','invalidated']}
    if d.empty:return pd.DataFrame(columns=SIGNAL_COLS),counts
    a=d[['ts','close','high','low','quote_volume','direction','atr','prior_high','prior_low','valid']].to_numpy(float)
    times=a[:,0].astype('int64');sides=np.nan_to_num(a[:,5]).astype(int)
    valid=(a[:,9]>0)&np.isfinite(a[:,[1,2,3,6,7,8]]).all(axis=1)&(a[:,6]>0)
    event=np.where(valid&(((sides==1)&(a[:,1]>a[:,7]))|((sides==-1)&(a[:,1]<a[:,8]))),sides,0)
    fresh=(event!=0)&(event!=np.r_[0,event[:-1]])
    local={(int(k[0]),int(k[2])):v for k,v in ranks.items() if k[1]==symbol}
    keys=times//H*H
    choices={(h,s):local.get((int(h),int(s))) for h,s in set(zip(keys,sides))}
    active=np.array([valid[j] and choices[(h,s)] is not None for j,(h,s) in enumerate(zip(keys,sides))])
    state=None;last_j=-2;records=[]
    for j in np.flatnonzero(active):
        if j!=last_j+1:state=None
        last_j=j;ts=int(times[j]);close,high,low,vol,side,atr,ph,pl=a[j,1:9];side=int(side)
        rank=choices[(keys[j],sides[j])]
        if state is not None:
            z=state;sg=z['side'];B=z['level'];A=z['atr']
            if ts-z['break_ts']>15*M:counts['expired']+=1;state=None
            elif side!=sg or sg*(close-B)<-.25*A:counts['invalidated']+=1;state=None
            elif acceptance and z['accept_ts'] is None:
                if sg*(close-B)>=.25*A:z['accept_ts']=ts;counts['accepted']+=1
            else:
                can_touch=(not acceptance or (ts>z['accept_ts'] and sg*(close-a[j-1,1])<0))
                if z['touch_ts'] is None and can_touch and low<=B+.25*A and high>=B-.25*A:
                    z['touch_ts']=ts;z['extreme']=low if sg==1 else high;counts['pullbacks']+=1
                if z['touch_ts'] is not None:
                    z['extreme']=min(z['extreme'],low) if sg==1 else max(z['extreme'],high)
                    if ts>z['touch_ts'] and sg*(close-B)>0 and (close>a[j-1,2] if sg==1 else close<a[j-1,3]):
                        records.append(dict(ts=ts,symbol=symbol,contract=contract,side=sg,signal_close=close,atr=A,stop_price=z['extreme']-sg*.1*A,level=B,break_ts=z['break_ts'],accept_ts=z['accept_ts'],touch_ts=z['touch_ts'],previous_quote_volume=vol,hour=ts//H*H,score=rank['score'],rank=rank['rank'],rvol=rank['rvol']))
                        counts['confirmations']+=1;state=None
            continue
        if fresh[j]:
            counts['breakouts']+=1;state=dict(side=side,level=ph if side==1 else pl,atr=atr,break_ts=ts,accept_ts=None,touch_ts=None)
    return pd.DataFrame(records,columns=SIGNAL_COLS),counts

def build():
    spec=read(ROOT/'protocol.json');reg=read(ROOT/'registration.json')
    assert sha(ROOT/'protocol.json')==reg['protocol_sha256']
    assert not (ROOT/'frozen.json').exists(),'Frozen feature data must not be regenerated'
    lo=int(pd.Timestamp(spec['start'],tz='UTC').timestamp()*1000);hi=int((pd.Timestamp(spec['end'],tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    mapping=read(SOURCE/'data-plan.json')['mapping'];quarantine=read(SOURCE/'quarantine.json')
    manifest=read(SOURCE/'data-manifest.json')
    assert sha(SOURCE/'data-manifest.json')==reg['source_manifest_sha256']
    btc=frame(load_contract('BTCUSDT','klines'))[1]
    # Reuse exactly the point-in-time universe and original availability decisions.
    universe=pd.read_parquet(BASE/'universe-hours.parquet')[['ts','symbol','liquidity_rank']]
    hours=[];archives=[]
    for i,(symbol,contract) in enumerate(mapping.items()):
        if not contract:continue
        raw,audit=load_extended(contract,manifest)
        if raw.empty:continue
        h=frame(raw)[1];h=enrich_hourly(raw,h,btc);h['symbol']=symbol;h['contract']=contract
        hours.append(h.reset_index(drop=True));archives.extend(audit)
        print('FACTORS',i,symbol,flush=True);del raw;gc.collect()
    allh=pd.concat(hours,ignore_index=True);allh.to_parquet(ROOT/'hourly.parquet',index=False)
    eligible=allh.merge(universe,on=['ts','symbol'],how='inner',validate='one_to_one')
    eligible.to_parquet(ROOT/'universe-hours.parquet',index=False)
    dump(ROOT/'archive-validation.json',{'count':len(archives),'unique_archives':len({x['archive'] for x in archives}),'all_identity_checks_passed':True,'records':archives})
    ranks={};events={k:[] for k in spec['versions']};audits={k:[] for k in spec['versions']}
    for key,cfg in spec['versions'].items():
        folder=ROOT/'runs'/key;folder.mkdir(parents=True,exist_ok=True)
        h=rank_hours(eligible,cfg);h.to_parquet(folder/'hourly-ranks.parquet',index=False)
        ranks[key]={(r['hour'],r['symbol'],r['side']):r for r in h.to_dict('records')}
        for name in ['regimes.parquet','quarantine.json']:shutil.copy2(BASE/name,folder/name)
        shutil.copy2(ROOT/'hourly.parquet',folder/'hourly.parquet')
        variant=dict(spec,variant=key,variant_config=cfg,ranking=str(cfg),entry='registered acceptance state machine' if cfg['acceptance'] else spec['entry'])
        dump(folder/'protocol.json',variant)
    for i,(symbol,contract) in enumerate(mapping.items()):
        if not contract:continue
        raw=load_contract(contract,'klines')
        if raw.empty:continue
        d=frame(raw)[0];d=d[d.ts.ge(lo)&d.ts.lt(hi)&d.ts.lt(quarantine.get(symbol,{}).get('known_ts',10**18))]
        for key,cfg in spec['versions'].items():
            sig,audit=signals_for(d,ranks[key],symbol,contract,cfg['acceptance'])
            if len(sig):events[key].append(sig)
            audits[key].append(dict(symbol=symbol,**audit))
        print('SIGNALS',i,symbol,flush=True);del raw,d;gc.collect()
    coverage=[]
    for key,cfg in spec['versions'].items():
        folder=ROOT/'runs'/key
        s=pd.concat(events[key],ignore_index=True).sort_values(['ts','symbol']) if events[key] else pd.DataFrame(columns=SIGNAL_COLS)
        s.to_parquet(folder/'signals.parquet',index=False);dump(folder/'signal-audit.json',audits[key])
        coverage.append({'variant':key,'label':cfg['label'],'rank_rows':len(ranks[key]),'signals':len(s),'selected_symbols':len({k[1] for k in ranks[key]})})
    dump(ROOT/'coverage.json',{'original_universe_hours':len(eligible),'residual_available_hours':int((eligible.residual_score.notna()&eligible.contract.ne('BTCUSDT')).sum()),'versions':coverage})
    print('FEATURES COMPLETE',coverage,flush=True)

if __name__=='__main__':build()
