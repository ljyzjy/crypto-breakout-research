"""Independent synthetic oracles; never reads real outcome market data."""
from pathlib import Path
import importlib.util
import hashlib
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('phase3_methods_audit', ROOT.parent/'incremental/methods.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
M = 60_000
checks = []

def record(name, fn):
    fn()
    checks.append({'name': name, 'passed': True})

def bars():
    ts = 1735689600000 + np.arange(90)*M
    op = 100 + np.arange(90)*0.1
    return pd.DataFrame(dict(ts=ts, open=op, high=op+.4, low=op-.3,
                             close=op+.1, volume=100., quote_volume=10_000.))

def events(d):
    return pd.DataFrame({'observation_id':['long','short'], 'symbol':['A','A'],
        'contract':['AUSDT','AUSDT'], 'decision_ts':[int(d.ts.iloc[3])]*2, 'side':[1,-1]})

def label_oracle():
    d = bars(); e = events(d); out = m.make_labels(e, d)
    assert np.all(out.entry_ts == d.ts.iloc[4])
    for h in (15,30,60):
        ep=d.open.iloc[4]; xp=d.open.iloc[4+h]
        hi=d.high.iloc[4:4+h].max(); lo=d.low.iloc[4:4+h].min()
        np.testing.assert_allclose(out[f'gross_bp_{h}'], [np.log(xp/ep)*10000, -np.log(xp/ep)*10000], rtol=1e-13)
        np.testing.assert_allclose(out[f'mfe_bp_{h}'], [max(0,np.log(hi/ep)*10000), max(0,np.log(ep/lo)*10000)], rtol=1e-13)
        np.testing.assert_allclose(out[f'mae_bp_{h}'], [max(0,np.log(ep/lo)*10000), max(0,np.log(hi/ep)*10000)], rtol=1e-13)
        assert out[f'label_valid_{h}'].all()

def path_missing_and_exit():
    d=bars(); e=events(d)
    zero=d.copy(); zero.loc[12,'volume']=0
    assert not m.make_labels(e,zero).label_valid_30.any()
    gap=d.drop(index=12)
    assert not m.make_labels(e,gap).label_valid_30.any()
    exit_unknown=d.copy(); exit_unknown.loc[34,['high','low','close','volume','quote_volume']]=np.nan
    assert m.make_labels(e,exit_unknown).label_valid_30.all()
    exit_unknown.loc[34,'open']=np.nan
    assert not m.make_labels(e,exit_unknown).label_valid_30.any()

def future_label_perturbation():
    d=bars(); e=events(d); out=m.make_labels(e,d,horizons=(30,))
    future=d.copy(); future.loc[future.ts>d.ts.iloc[34], ['open','high','low','close']]*=100
    pd.testing.assert_frame_equal(out,m.make_labels(e,future,horizons=(30,)))

def design(n=400):
    rng=np.random.default_rng(776)
    f=pd.DataFrame({'symbol':np.resize(['A','B','C'],n), 'side':np.resize([-1,1],n),
        'r6':rng.normal(size=n), 'btc_r6':rng.normal(size=n), 'residual6':rng.normal(size=n),
        'vol24':rng.uniform(.1,1,n), 'quote_rvol':rng.uniform(0,5,n), 'count_rvol':rng.uniform(0,5,n),
        'utc_hour_sin':rng.normal(size=n), 'utc_hour_cos':rng.normal(size=n),
        'decision_ts':1735689600000+np.arange(n)*M})
    f['observation_id']=[str(i) for i in range(n)]
    return f

def train_only_and_new_coin():
    f=design(); cut=int(f.decision_ts.iloc[250]); mask=m.temporal_mask(f,int(f.decision_ts.min()),cut)
    y=3*f.side*f.r6+.2*f.side*f.residual6
    model=m.fit_ols(f.loc[mask],y.loc[mask],m.BASE+m.GROUPS['F1'])
    mutated=f.copy(); mutated.loc[~mask,'r6']=1e12; mutated.loc[~mask,'symbol']='FUTURE_COIN'
    ym=y.copy(); ym.loc[~mask]=-1e13
    other=m.fit_ols(mutated.loc[mask],ym.loc[mask],m.BASE+m.GROUPS['F1'])
    assert model==other
    assert 'FUTURE_COIN' not in model['coin_levels']
    new=f.iloc[:1].copy(); ref=new.copy(); new.symbol='UNSEEN'; ref.symbol=model['reference_coin']
    a,valid,unseen=m.predict_ols(new,model); b,_,_=m.predict_ols(ref,model)
    np.testing.assert_allclose(a,b,rtol=0,atol=0)
    assert valid.all() and unseen.all()

def purge_oracle():
    cutoff=1735776000000
    f=pd.DataFrame({'decision_ts':[cutoff-66*M,cutoff-65*M,cutoff-64*M,cutoff-60*M,cutoff]})
    assert m.temporal_mask(f,cutoff-24*60*M,cutoff).tolist()==[True,False,False,False,False]
    accepted=f.loc[m.temporal_mask(f,cutoff-24*60*M,cutoff)]
    assert ((accepted.decision_ts+61*M)<cutoff).all()

def equal_coin_day_and_holm():
    f=pd.DataFrame({'decision_ts':[0,0,0,86_400_000], 'symbol':['A','A','B','A']})
    y=np.zeros(4); base=np.array([1.,3.,2.,4.]); enhanced=np.zeros(4)
    out=m.daily_loss(f,y,base,enhanced,0,3*86_400_000)
    assert out.difference.iloc[0]==4.5  # A mean5, B mean4; not raw-observation mean14/3.
    assert out.difference.iloc[1]==16 and np.isnan(out.difference.iloc[2])
    p={'F1':.001,'F2':.01,'F3':.04,'F4':1.,'F5':.2,'F6':.03}
    assert m.holm(p)=={'F1':.006,'F2':.05,'F6':.12,'F3':.12,'F5':.4,'F4':1.}

if __name__=='__main__':
    for name,fn in [('direction_and_MAE_MFE_oracle',label_oracle),
        ('missing_held_minute_vs_exit_open_only',path_missing_and_exit),
        ('label_invariant_to_post_exit_future',future_label_perturbation),
        ('train_only_scales_FE_and_future_mutation',train_only_and_new_coin),
        ('65minute_purge_and_strict_label_boundary',purge_oracle),
        ('coin_day_equal_weights_and_Holm6',equal_coin_day_and_holm)]: record(name,fn)
    result={'created_utc':datetime.now(timezone.utc).isoformat(), 'checks':checks,
        'methods_sha256':hashlib.sha256((ROOT.parent/'incremental/methods.py').read_bytes()).hexdigest(),
        'actual_market_labels_read':False, 'actual_account_returns_computed':False,
        'scope_limit':'Method-level finite synthetic checks, not proof of real-data driver chronology or all execution paths.'}
    (ROOT/'synthetic_methods.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
