"""Predeclared local identification sensitivity, no outcome labels or PnL."""
from pathlib import Path
from datetime import datetime,timezone
import sys,importlib.util,json,hashlib
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];OUT=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
f=load('phase2_stability_features',ROOT/'features.py');io=load('phase2_stability_data',ROOT/'data_io.py')
FEATURE_HASH_AT_START=hashlib.sha256((ROOT/'features.py').read_bytes()).hexdigest()
MINUTE=60000;DAY=86400000
START=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000);END=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)
pools=io.load_daily_pools();mapping=io.load_mapping();q=io.load_quarantine()
days={c:set() for c in io.list_contracts()}
for r in pools:
    for item in r['pool']:
        c=mapping.get(item['symbol'])
        if c in days:days[c].add(r['date'])

def quarantine(contract):
    v=q.get(contract)
    if v is None:return None
    return int(v['known_ts'] if isinstance(v,dict) else v)
def eligibility(h,contract):
    dates=pd.to_datetime(h.ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    m=h.ts.ge(START)&h.ts.lt(END)&dates.isin(days[contract])
    qt=quarantine(contract)
    if qt is not None:m &= h.ts.lt(qt)
    return m
def corr(x,y):
    if len(x)<2 or np.std(x)==0 or np.std(y)==0:return None
    return float(np.corrcoef(x,y)[0,1])
def numeric(a,b,cols):
    joined=a[['ts']+cols].reset_index(drop=True).merge(b[['ts']+cols].reset_index(drop=True),on='ts',suffixes=('_base','_variant'),validate='one_to_one')
    out={}
    for col in cols:
        x=joined[col+'_base'].to_numpy();y=joined[col+'_variant'].to_numpy();v=np.isfinite(x)&np.isfinite(y);x=x[v];y=y[v]
        out[col]={'common_finite':len(x),'base_finite':int(np.isfinite(joined[col+'_base']).sum()),'variant_finite':int(np.isfinite(joined[col+'_variant']).sum()),'pearson':corr(x,y),'spearman':corr(pd.Series(x).rank().to_numpy(),pd.Series(y).rank().to_numpy()),'sign_disagreement_fraction':float((np.sign(x)!=np.sign(y)).mean()) if len(x) else None,'median_absolute_delta':float(np.median(abs(x-y))) if len(x) else None,'p95_absolute_delta':float(np.quantile(abs(x-y),.95)) if len(x) else None}
    return out,joined

def event_comparison(base,variant):
    # Compare event initiation keys, not IDs which may include the window parameter.
    a={(int(r.t0_open_ts),int(r.side)) for r in base.itertuples()};b={(int(r.t0_open_ts),int(r.side)) for r in variant.itertuples()}
    intersection=a&b;union=a|b
    # One-to-one local nearest matching for shifted event clocks, not a claim of same economic event.
    candidates=[]
    for side in (-1,1):
        aa=np.array(sorted(t for t,s in a if s==side),dtype=np.int64);bb=np.array(sorted(t for t,s in b if s==side),dtype=np.int64)
        for t in aa:
            k=np.searchsorted(bb,t)
            for j in (k-1,k):
                if 0<=j<len(bb) and abs(int(bb[j])-int(t))<=15*MINUTE:candidates.append((abs(int(bb[j])-int(t)),int(t),int(bb[j]),side))
    useda=set();usedb=set();shifts=[]
    for delta,t,u,side in sorted(candidates):
        if (t,side) in useda or (u,side) in usedb:continue
        useda.add((t,side));usedb.add((u,side));shifts.append((u-t)/MINUTE)
    return {'base_events':len(a),'variant_events':len(b),'exact_intersection':len(intersection),'union':len(union),'jaccard':len(intersection)/len(union) if union else None,'base_retained_fraction':len(intersection)/len(a) if a else None,'base_lost':len(a-b),'variant_added':len(b-a),'nearest_one_to_one_within15m_pairs':len(shifts),'median_absolute_start_shift_minutes':float(np.median(np.abs(shifts))) if shifts else None,'p95_absolute_start_shift_minutes':float(np.quantile(np.abs(shifts),.95)) if shifts else None}

contracts=sorted(days)
if '--sample' in sys.argv:contracts=[c for c in ('BTCUSDT','ETHUSDT','1000PEPEUSDT','AXSUSDT','BIOUSDT','FTMUSDT') if c in days]
btc=io.load_minutes('BTCUSDT');btc_h={k:f.compute_hourly(btc,is_btc=True,background_hours=k) for k in (5,6,7)}
hour_records=[];event_records=[];joined_parts={5:[],7:[]}
for i,contract in enumerate(contracts,1):
    m=io.load_minutes(contract);ctx=f.compute_minute_context(m)
    hs={k:f.compute_hourly(m,btc_hourly=btc_h[k],is_btc=contract=='BTCUSDT',background_hours=k) for k in (5,6,7)}
    hs={k:h[eligibility(h,contract)] for k,h in hs.items()}
    for k in (5,7):
        stats,j=numeric(hs[6],hs[k],['r6','residual6','efficiency6','concentration6']);j['contract']=contract;joined_parts[k].append(j)
        hour_records.append({'contract':contract,'variant_hours':k,'eligible_hours':len(hs[6]),'variables':stats})
    ev={k:f.build_event_rows(m,context=ctx,eligible_days=days[contract],known_quarantine_ts=quarantine(contract),lookback=k,start_ms=START,end_ms=END) for k in (15,20,25)}
    for k in (15,25):event_records.append({'contract':contract,'variant_lookback_minutes':k,**event_comparison(ev[20],ev[k])})
    print('STABILITY',i,'/',len(contracts),contract,flush=True)
    (OUT/'stability-progress.json').write_text(json.dumps({'completed':i,'total':len(contracts),'last_contract':contract}),encoding='utf-8')

aggregate_hour=[]
for k,frames in joined_parts.items():
    j=pd.concat(frames,ignore_index=True);out={}
    for col in ('r6','residual6','efficiency6','concentration6'):
        x=j[col+'_base'].to_numpy();y=j[col+'_variant'].to_numpy();v=np.isfinite(x)&np.isfinite(y);x=x[v];y=y[v]
        out[col]={'common_finite':int(v.sum()),'pearson':corr(x,y),'spearman':corr(pd.Series(x).rank().to_numpy(),pd.Series(y).rank().to_numpy()),'sign_disagreement_fraction':float((np.sign(x)!=np.sign(y)).mean()) if len(x) else None,'median_absolute_delta':float(np.median(abs(x-y))) if len(x) else None,'p95_absolute_delta':float(np.quantile(abs(x-y),.95)) if len(x) else None}
    aggregate_hour.append({'variant_hours':k,'variables':out})
aggregate_event=[]
for k in (15,25):
    rows=[x for x in event_records if x['variant_lookback_minutes']==k]
    sums={col:sum(r[col] for r in rows) for col in ('base_events','variant_events','exact_intersection','union','base_lost','variant_added','nearest_one_to_one_within15m_pairs')}
    sums['jaccard']=sums['exact_intersection']/sums['union'] if sums['union'] else None
    sums['base_retained_fraction']=sums['exact_intersection']/sums['base_events'] if sums['base_events'] else None
    aggregate_event.append({'variant_lookback_minutes':k,**sums})
assert hashlib.sha256((ROOT/'features.py').read_bytes()).hexdigest()==FEATURE_HASH_AT_START,'Feature source changed during audit; rerun required'
payload={'utc':datetime.now(timezone.utc).isoformat(),'scope':'All mapped contracts' if '--sample' not in sys.argv else 'Deterministic 6-contract sample','contracts':contracts,'windows':{'background_hours':[5,6,7],'boundary_minutes':[15,20,25]},'vary_one_dimension_at_a_time':True,'fixed_residual_note':'Only the background r6/efficiency/concentration and BTC background horizon varies. The residual signal,720h fit,6h exclusion and24h scale remain fixed; unchanged residual correlation is by construction, not evidence of robustness to its own windows.','event_count_scope':'Initiated events known before study end, including failed or incomplete measurement events, are counted for identification sensitivity; this is not a traded sample.','profit_or_forward_labels_computed':False,'new_parameter_selection':False,'aggregate_hourly':aggregate_hour,'aggregate_events':aggregate_event,'by_contract_hourly':hour_records,'by_contract_events':event_records,'features_sha256':FEATURE_HASH_AT_START,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'interpretation':'Sensitivity is reported, not optimized. Correlation or event overlap does not establish predictive value or profitability. Nearest matching is descriptive and does not identify the same economic event.'}
(OUT/'stability.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({'contracts':len(contracts),'complete':True}))
