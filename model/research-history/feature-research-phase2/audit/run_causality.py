"""Independent deterministic causality/oracle checks; no forward returns or PnL."""
from pathlib import Path
import importlib.util,sys,json,hashlib,traceback
from datetime import datetime,timezone
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent
MINUTE=60_000;HOUR=60*MINUTE
ATOL=1e-10;RTOL=1e-9
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
f=module('phase2_audited_features',ROOT/'features.py')
results=[]
def check(name,fn):
    try:
        detail=fn();results.append({'test':name,'passed':True,'detail':detail})
    except Exception as e:
        results.append({'test':name,'passed':False,'error':repr(e),'traceback':traceback.format_exc()})
    print(name,results[-1]['passed'],flush=True)

def synthetic(seed=21,hours=840,beta=1.,btc=None):
    n=hours*60;rng=np.random.default_rng(seed)
    if btc is None:r=rng.normal(0.000001,0.00013,n)
    else:
        b=np.log(btc.close.to_numpy()/btc.close.shift(1).to_numpy());b[0]=0
        r=0.0000007+beta*b+rng.normal(0,0.00005,n)
    close=100*np.exp(np.cumsum(r));open_=np.r_[close[0],close[:-1]]
    spread=0.01+0.02*rng.random(n)
    volume=10+rng.random(n)*20;quote=volume*close;counts=100+rng.integers(0,100,n)
    start=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
    return pd.DataFrame({'ts':start+np.arange(n,dtype=np.int64)*MINUTE,'open':open_,'high':np.maximum(open_,close)+spread,'low':np.minimum(open_,close)-spread,'close':close,'volume':volume,'quote_volume':quote,'trade_count':counts,'taker_buy_quote_volume':quote*.5})

def at_ts(d,t):
    r=d.loc[d.ts.eq(t)]
    assert len(r)==1,(t,len(r));return r.iloc[0]
def finite_cols(d,cols):return [x for x in cols if x in d]
def assert_equal(a,b,cols,key='ts'):
    a=a.reset_index(drop=True).sort_values(key).reset_index(drop=True);b=b.reset_index(drop=True).sort_values(key).reset_index(drop=True)
    assert a[key].tolist()==b[key].tolist(),(len(a),len(b),key)
    for c in cols:
        np.testing.assert_allclose(a[c].to_numpy(dtype=float),b[c].to_numpy(dtype=float),atol=ATOL,rtol=RTOL,equal_nan=True,err_msg=c)
    return len(a)
def perturb_after(d,cut):
    z=d.copy();mask=z.ts.ge(cut);n=int(mask.sum());mult=np.exp(np.linspace(.02,.8,n))
    for c in ('open','high','low','close'):z.loc[mask,c]=z.loc[mask,c].to_numpy()*mult
    for c in ('volume','quote_volume','trade_count','taker_buy_quote_volume'):z.loc[mask,c]=z.loc[mask,c].to_numpy()*3
    return z

btc=synthetic();alt=synthetic(seed=22,beta=1.4,btc=btc)
bh=f.compute_hourly(btc,is_btc=True);ah=f.compute_hourly(alt,btc_hourly=bh)
HCOLS=['r6','residual6','efficiency6','concentration6','quote_rvol','count_rvol','vol24','btc_r6']
MCOLS=['atr14','range_atr','rv_relative60']
ECOLS=['B','A','side','boundary_distance','outside_fraction5','drawdown_atr','recovery_fraction']

def hourly_oracle():
    close=alt.set_index(pd.to_datetime(alt.ts,unit='ms',utc=True)).close.resample('1h',label='right',closed='left').last()
    bc=btc.set_index(pd.to_datetime(btc.ts,unit='ms',utc=True)).close.resample('1h',label='right',closed='left').last()
    r=np.log(close).diff();b=np.log(bc).diff()
    j=800;t=int(r.index[j].timestamp()*1000);row=at_ts(ah,t)
    recent=r.iloc[j-5:j+1].to_numpy();np.testing.assert_allclose(row.r6,recent.sum(),atol=ATOL,rtol=RTOL)
    np.testing.assert_allclose(row.efficiency6,abs(recent.sum())/abs(recent).sum(),atol=ATOL,rtol=RTOL)
    np.testing.assert_allclose(row.concentration6,abs(recent).max()/abs(recent).sum(),atol=ATOL,rtol=RTOL)
    # Last training return ends at j-6, 720 observations inclusive.
    ys=r.iloc[j-6-719:j-6+1].to_numpy();xs=b.iloc[j-6-719:j-6+1].to_numpy()
    coeff=np.linalg.lstsq(np.column_stack([np.ones(720),xs]),ys,rcond=None)[0]
    alpha,beta=coeff;last24=r.iloc[j-23:j+1].to_numpy()-alpha-beta*b.iloc[j-23:j+1].to_numpy()
    residual=(recent.sum()-6*alpha-beta*b.iloc[j-5:j+1].sum())/(np.sqrt(6)*np.std(last24,ddof=1))
    np.testing.assert_allclose(row.residual6,residual,atol=ATOL,rtol=RTOL)
    return {'decision_ms':t,'ols_window':720,'excluded_recent_hours':6,'oracle_residual6':float(residual),'actual':float(row.residual6)}

def minute_oracle():
    c=f.compute_minute_context(alt);j=30000+17;t=int(alt.ts.iloc[j]);r=at_ts(c,t)
    d=alt.iloc[:j].copy();d.index=pd.to_datetime(d.ts,unit='ms',utc=True)
    bars=d.resample('15min',label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','ts':'count'})
    bars=bars[(bars.index<=pd.Timestamp(t,unit='ms',tz='UTC'))&bars.ts.eq(15)]
    tr=np.maximum(bars.high-bars.low,np.maximum(abs(bars.high-bars.close.shift(1)),abs(bars.low-bars.close.shift(1))))
    atr=float(tr.tail(14).mean());np.testing.assert_allclose(r.atr14,atr,atol=ATOL,rtol=RTOL)
    np.testing.assert_allclose(r.range_atr,(alt.high.iloc[j]-alt.low.iloc[j])/atr,atol=ATOL,rtol=RTOL)
    return {'minute_open_ms':t,'atr_known_ms':int(r.atr_known_ts),'atr_oracle':atr,'range_oracle':float(r.range_atr)}

def prefix_hourly():
    counts=[]
    for hour,extra in ((100,17),(730,13),(810,47)):
        cut=int(alt.ts.iloc[hour*60+extra]);bp=f.compute_hourly(btc,asof_ms=cut,is_btc=True);ap=f.compute_hourly(alt,btc_hourly=bp,asof_ms=cut)
        full=ah[ah.ts.le(cut)];published=ap[ap.ts.le(cut)]
        counts.append(assert_equal(full,published,HCOLS))
        mutated=f.compute_hourly(perturb_after(alt,cut),btc_hourly=f.compute_hourly(perturb_after(btc,cut),is_btc=True))
        counts.append(assert_equal(full,mutated[mutated.ts.le(cut)],HCOLS))
    return {'hour_rows_compared':sum(counts),'cutoffs':3,'prefix_and_future_mutation':True}

def prefix_minute():
    base=f.compute_minute_context(alt);counts=[]
    for j in (20001,44003,49007):
        cut=int(alt.ts.iloc[j]);expected=base[base.decision_ts.le(cut)]
        truncated=f.compute_minute_context(alt,asof_ms=cut)
        counts.append(assert_equal(expected,truncated[truncated.decision_ts.le(cut)],MCOLS))
        modified=f.compute_minute_context(perturb_after(alt,cut))
        counts.append(assert_equal(expected,modified[modified.decision_ts.le(cut)],MCOLS))
    return {'minute_rows_compared':sum(counts),'cutoffs':3}

def current_bar_hidden():
    cut=int(alt.ts.iloc[48_005])+30_000
    norm=f.normalize_minutes(alt,asof_ms=cut)
    assert norm.index.max().value//1_000_000+MINUTE<=cut
    h=f.compute_hourly(alt,btc_hourly=bh,asof_ms=cut)
    assert int(h.ts.max())<=cut
    c=f.compute_minute_context(alt,asof_ms=cut)
    assert int(c.decision_ts.max())<=cut
    return {'asof_inside_minute':cut,'last_hour':int(h.ts.max()),'last_minute_decision':int(c.decision_ts.max())}

def gap_zero_flat():
    j=800*60+3;hour_end=int(alt.ts.iloc[j]//HOUR*HOUR+HOUR)
    gap=alt.drop(index=j);hg=f.compute_hourly(gap,btc_hourly=bh)
    assert not bool(at_ts(hg,hour_end).hour_valid)
    zero=alt.copy();zero.loc[j,['volume','quote_volume']]=0;hz=f.compute_hourly(zero,btc_hourly=bh)
    assert not bool(at_ts(hz,hour_end).hour_valid)
    assert np.isnan(at_ts(hg,hour_end).r6) and np.isnan(at_ts(hz,hour_end).r6)
    flat=alt.copy();flat[['open','high','low','close']]=100
    hf=f.compute_hourly(flat,btc_hourly=bh);last=hf.iloc[-1]
    assert last.r6==0 and np.isnan(last.efficiency6) and np.isnan(last.concentration6)
    assert bh.residual6.isna().all()
    assert ah[ah.ts<alt.ts.iloc[726*60]].residual6.isna().all()
    return {'missing_minute_invalidates_hour':True,'zero_volume_invalidates_hour':True,'flat_path_denominator_na':True,'btc_self_residual_na':True,'short_history_na':True}

def event_data(failed=False,mirror=False):
    n=460;start=int(pd.Timestamp('2025-02-01',tz='UTC').timestamp()*1000)
    d=pd.DataFrame({'ts':start+np.arange(n)*MINUTE,'open':100.,'high':100.1,'low':99.9,'close':100.,'volume':10.,'quote_volume':1000.,'trade_count':100.,'taker_buy_quote_volume':500.})
    rows=[(100.,100.5,100.,100.4),(100.4,100.6,100.35,100.5),(100.5,100.5,100.,100.1),(100.1,100.3,100.,100.2),(100.2,100.55,100.15,100.45),(100.45,100.5,99.9 if failed else 100.25,99.95 if failed else 100.3)]
    for i,v in enumerate(rows,300):d.loc[i,['open','high','low','close']]=v
    if mirror:
        old=d[['open','high','low','close']].copy();d.open=200-old.open;d.close=200-old.close;d.high=200-old.low;d.low=200-old.high
    return d

def chosen_event(d,**kw):
    e=f.build_event_rows(d,**kw);wanted=int(d.ts.iloc[300]);row=e[e.t0_open_ts.eq(wanted)]
    assert len(row)==1,(list(e.columns),len(e),e.head().to_dict('records'));return e,row.iloc[0]

def event_oracle():
    d=event_data();e,r=chosen_event(d)
    np.testing.assert_allclose([r.B,r.A,r.boundary_distance,r.outside_fraction5,r.drawdown_atr,r.recovery_fraction],[100.1,.2,1.,.8,1.5,.5],atol=ATOL,rtol=RTOL)
    assert r.decision_ts==d.ts.iloc[300]+6*MINUTE
    _,m=chosen_event(event_data(mirror=True))
    assert m.side==-1 and r.side==1
    np.testing.assert_allclose([m.A,m.boundary_distance,m.outside_fraction5,m.drawdown_atr,m.recovery_fraction],[r.A,r.boundary_distance,r.outside_fraction5,r.drawdown_atr,r.recovery_fraction],atol=ATOL,rtol=RTOL)
    _,bad=chosen_event(event_data(failed=True));assert np.isfinite(bad.boundary_distance) and bad.boundary_distance<0
    return {'long_short_mirror':True,'failed_break_kept':True,'event_id':str(r.event_id),'decision_ms':int(r.decision_ts)}

def event_prefix():
    d=event_data();full,r=chosen_event(d);cut=int(r.decision_ts)
    for earlier in (cut-2*MINUTE,cut-MINUTE,cut-1):
        e=f.build_event_rows(d,asof_ms=earlier);v=e[e.t0_open_ts.eq(r.t0_open_ts)]
        assert len(v)==1 and v.iloc[0].event_status=='pending_measurement'
        assert v[['boundary_distance','outside_fraction5','drawdown_atr','recovery_fraction']].isna().all().all()
    trunc=f.build_event_rows(d,asof_ms=cut);mut=f.build_event_rows(perturb_after(d,cut))
    assert_equal(full[full.decision_ts.le(cut)],trunc[trunc.decision_ts.le(cut)],ECOLS,key='event_id')
    assert_equal(full[full.decision_ts.le(cut)],mut[mut.decision_ts.le(cut)],ECOLS,key='event_id')
    return {'no_publish_before_t0_plus6m':True,'prefix_stable':True,'future_ohlcv_mutation_stable':True}

def event_gap_dedup():
    d=event_data();gap=d.drop(index=303);e,r=chosen_event(gap)
    assert not np.isfinite(r.boundary_distance)
    # Another eligible breakout within sixty minutes cannot create a second retained event.
    d2=d.copy();d2.loc[330,['open','high','low','close']]=[100.,101.2,99.9,101.]
    e=f.build_event_rows(d2);t=int(d2.ts.iloc[300]);assert len(e[(e.t0_open_ts>=t)&(e.t0_open_ts<t+60*MINUTE)])==1
    # A known quarantine only affects events after its actual known time.
    e=f.build_event_rows(d,known_quarantine_ts=t-MINUTE)
    assert not e.t0_open_ts.eq(t).any()
    return {'post_break_missing_bar_retained_na':True,'sixty_minute_dedup':True,'known_quarantine_enforced':True}

def rvol_oracle():
    j=800;t=int(ah.ts.iloc[j]);row=ah.iloc[j]
    d=alt.copy();d.index=pd.to_datetime(d.ts,unit='ms',utc=True)
    sums=d.resample('1h',closed='left',label='right')[['quote_volume','trade_count']].sum()
    dt=pd.Timestamp(t,unit='ms',tz='UTC');hist=[dt-pd.Timedelta(days=k) for k in range(1,21)]
    for col,target in [('quote_volume','quote_rvol'),('trade_count','count_rvol')]:
        value=sums.loc[dt,col]/sums.loc[hist,col].median();np.testing.assert_allclose(row[target],value,atol=ATOL,rtol=RTOL)
    return {'same_utc_hour_references':20,'current_hour_excluded_from_baseline':True}

def relative_rv_oracle():
    c=f.compute_minute_context(alt);r=np.diff(np.log(alt.close.to_numpy()),prepend=np.nan)
    rows=[]
    for j in (780*60+29,800*60+12):
        now=np.sqrt(np.sum(r[j-59:j+1]**2))
        history=[np.sqrt(np.sum(r[j-k*1440-59:j-k*1440+1]**2)) for k in range(1,21)]
        expected=now/np.median(history);actual=float(at_ts(c,int(alt.ts.iloc[j])).rv_relative60)
        np.testing.assert_allclose(actual,expected,atol=ATOL,rtol=RTOL)
        rows.append({'decision_ms':int(alt.ts.iloc[j])+MINUTE,'expected':expected,'actual':actual})
    return {'half_hour_and_arbitrary_phase':rows,'previous_days':20}

def atr_gap_requires_previous_close():
    d=event_data();d.loc[224,['volume','quote_volume']]=0
    c=f.compute_minute_context(d);row=at_ts(c,int(d.ts.iloc[240]))
    # Quarter ending225m is invalid; next quarter TR at240m lacks prior close.
    assert np.isnan(row.atr14)
    return {'previous_quarter_missing_prevents_high_low_fallback':True}

def pending_future_membership_hidden():
    d=event_data();d.ts += int(pd.Timedelta(hours=18,minutes=58).total_seconds()*1000)
    t=int(d.ts.iloc[300]);cut=t+MINUTE;decision=t+6*MINUTE
    first_day=pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d')
    e,r=chosen_event(d,eligible_days={first_day},known_quarantine_ts=decision-MINUTE,asof_ms=cut)
    assert r.event_status=='pending_measurement'
    assert pd.isna(r.eligible_decision) and pd.isna(r.quarantined)
    full,completed=chosen_event(d,eligible_days={first_day},known_quarantine_ts=decision-MINUTE)
    assert not bool(completed.eligible_decision) and bool(completed.quarantined)
    assert np.isfinite(completed.boundary_distance)
    return {'pending_future_day_eligibility_unknown':True,'pending_future_quarantine_unknown':True,'completed_ineligible_event_retained_with_features':True}

def real_checks():
    io=module('phase2_audit_data_io',ROOT/'data_io.py');out=[]
    for contract in ('BTCUSDT','ETHUSDT','1000PEPEUSDT','AXSUSDT','BIOUSDT','FTMUSDT'):
        raw=io.load_minutes(contract);start=int(raw.ts.min());cut=start+800*HOUR+17*MINUTE
        selection='first available840h; cutoff800h17m'
        if contract=='FTMUSDT' and raw.volume.eq(0).any():
            first_zero=int(raw.loc[raw.volume.eq(0),'ts'].iloc[0]);start=max(start,first_zero-800*HOUR);cut=first_zero+17*MINUTE
            selection='first observed zero-volume minute, with up to800h prior history; cutoff17m later'
        end=cut+40*HOUR
        raw=raw[(raw.ts>=start)&(raw.ts<end)].copy();bm=io.load_minutes('BTCUSDT',start_ms=start-HOUR,end_ms=end)
        bh=f.compute_hourly(bm,is_btc=True);hh=f.compute_hourly(raw,btc_hourly=bh,is_btc=contract=='BTCUSDT')
        bp=f.compute_hourly(bm,is_btc=True,asof_ms=cut);hp=f.compute_hourly(raw,btc_hourly=bp,is_btc=contract=='BTCUSDT',asof_ms=cut)
        n=assert_equal(hh[hh.ts.le(cut)],hp[hp.ts.le(cut)],HCOLS)
        hm=f.compute_hourly(perturb_after(raw,cut),btc_hourly=f.compute_hourly(perturb_after(bm,cut),is_btc=True),is_btc=contract=='BTCUSDT')
        assert_equal(hh[hh.ts.le(cut)],hm[hm.ts.le(cut)],HCOLS)
        tail=raw[raw.ts.ge(cut-48*HOUR)].copy();ctx=f.compute_minute_context(tail);ev=f.build_event_rows(tail,context=ctx)
        ep=f.build_event_rows(tail,asof_ms=cut);em=f.build_event_rows(perturb_after(tail,cut))
        pub=ev[(ev.decision_ts<=cut)&ev.event_status.ne('pending_measurement')]
        assert_equal(pub,ep[(ep.decision_ts<=cut)&ep.event_status.ne('pending_measurement')],ECOLS,key='event_id')
        assert_equal(pub,em[(em.decision_ts<=cut)&em.event_status.ne('pending_measurement')],ECOLS,key='event_id')
        cp=f.compute_minute_context(tail,asof_ms=cut);cm=f.compute_minute_context(perturb_after(tail,cut))
        mc=assert_equal(ctx[ctx.decision_ts.le(cut)],cp[cp.decision_ts.le(cut)],MCOLS)
        assert_equal(ctx[ctx.decision_ts.le(cut)],cm[cm.decision_ts.le(cut)],MCOLS)
        out.append({'contract':contract,'selection_rule':selection,'input_rows':len(raw),'zero_volume_rows':int(raw.volume.eq(0).sum()),'start_ms':start,'cut_ms':cut,'hour_rows_checked':n,'minute_rows_checked':mc,'published_event_rows_checked':len(pub),'residual_available_checked':int(hh[hh.ts.le(cut)].residual6.notna().sum())})
    return out

def repaired_residual_real_checks():
    io=module('phase2_repaired_audit_data_io',ROOT/'data_io.py');out=[]
    pools=io.load_daily_pools();mapping=io.load_mapping()
    for contract in ('AXSUSDT','BIOUSDT'):
        raw=io.load_minutes(contract);start=int(raw.ts.min());end=int(raw.ts.max())+MINUTE
        bm=io.load_minutes('BTCUSDT',start_ms=start-HOUR,end_ms=end)
        bh=f.compute_hourly(bm,is_btc=True);hh=f.compute_hourly(raw,btc_hourly=bh)
        finite=hh[hh.residual6.notna()]
        allowed_days={r['date'] for r in pools if any(mapping.get(item['symbol'])==contract for item in r['pool'])}
        eligible=pd.to_datetime(hh.ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d').isin(allowed_days)
        record={'contract':contract,'all_input_hours':len(hh),'finite_residual_all_hours':len(finite),'finite_residual_qualified_hours':int((hh.residual6.notna()&eligible).sum()),'selection':'earliest finite residual, availability only; never selected by returns'}
        if finite.empty:
            record['status']='no_finite_residual_after_warmup; no repaired-finite-path claim'
            out.append(record);continue
        first=int(finite.ts.iloc[0]);cut=first+17*MINUTE
        bp=f.compute_hourly(bm,is_btc=True,asof_ms=cut);hp=f.compute_hourly(raw,btc_hourly=bp,asof_ms=cut)
        n=assert_equal(hh[hh.ts.le(cut)],hp[hp.ts.le(cut)],HCOLS)
        mutated=f.compute_hourly(perturb_after(raw,cut),btc_hourly=f.compute_hourly(perturb_after(bm,cut),is_btc=True))
        assert_equal(hh[hh.ts.le(cut)],mutated[mutated.ts.le(cut)],HCOLS)
        before=at_ts(hh,first).residual6;after=at_ts(hp,first).residual6
        np.testing.assert_allclose(before,after,atol=ATOL,rtol=RTOL)
        record.update(status='finite_path_prefix_and_future_mutation_passed',first_finite_ms=first,cut_ms=cut,hour_rows_checked=n,finite_rows_checked=int(hp.residual6.notna().sum()),future_input_rows_mutated=int(raw.ts.ge(cut).sum()),first_residual=float(before))
        out.append(record)
    return out

check('independent_hourly_OLS_and_path_oracle',hourly_oracle)
check('independent_closed_15m_ATR_oracle',minute_oracle)
check('hourly_prefix_and_future_mutation',prefix_hourly)
check('minute_prefix_and_future_mutation',prefix_minute)
check('incomplete_current_minute_and_higher_bars_hidden',current_bar_hidden)
check('missing_zero_flat_short_history_and_BTC',gap_zero_flat)
check('event_oracle_mirror_and_failed_break',event_oracle)
check('event_publication_prefix_future_mutation',event_prefix)
check('event_gap_dedup_quarantine',event_gap_dedup)
check('same_UTC_RVOL_oracle',rvol_oracle)
check('rolling_60m_RV_same_minute_phase_oracle',relative_rv_oracle)
check('ATR_previous_quarter_gap_is_not_filled',atr_gap_requires_previous_close)
check('pending_future_pool_and_quarantine_unknown',pending_future_membership_hidden)
if '--real' in sys.argv:
    check('deterministic_real_contract_prefix_mutation',real_checks)
    check('repaired_AXS_BIO_finite_residual_prefix_mutation',repaired_residual_real_checks)
payload={'utc':datetime.now(timezone.utc).isoformat(),'scope':'Independent finite synthetic/oracle tests plus specified real contracts if requested. No strategy returns, forward labels, optimization or current simulator changes.','all_passed':all(x['passed'] for x in results),'tests':results,'features_sha256':hashlib.sha256((ROOT/'features.py').read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'numeric_tolerance':{'abs':ATOL,'rel':RTOL},'proof_limit':'These checks establish the tested cases and code review scope; not exhaustive proof of every possible input or live message timing.'}
(OUT/'causality.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({'tests':len(results),'passed':sum(x['passed'] for x in results),'all_passed':payload['all_passed']}))
