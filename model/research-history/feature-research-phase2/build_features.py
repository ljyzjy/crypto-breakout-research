"""Build only causal features and research opportunity cohorts, without outcomes."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,gc,hashlib,json
import numpy as np
import pandas as pd
from features import (M,H,D,FEATURES,HOURLY_FEATURES,EVENT_FEATURES,compute_hourly,
                      compute_minute_context,build_event_rows)
import data_io

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]
OUT=ROOT/'feature_outputs'
START=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
END=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)

def dump(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def attach_context(rows,h,ctx):
    rows=rows.copy()
    if rows.empty:return rows
    dec=rows.decision_ts.to_numpy(dtype=np.int64)
    hourkeys=dec//H*H
    if len(h):hh=h.reindex(hourkeys).reset_index(drop=True)
    else:hh=pd.DataFrame(index=range(len(rows)),columns=HOURLY_FEATURES+['vol24','btc_r6','hour_valid','regression_pairs'])
    for col in HOURLY_FEATURES+['vol24','btc_r6','hour_valid','regression_pairs']:
        rows[col]=pd.to_numeric(pd.Series(hh[col].to_numpy(),index=rows.index),errors='coerce')
    cc=ctx.reindex(dec-M).reset_index(drop=True)
    for col in ['rv_relative60','range_atr']:
        rows[col]=pd.to_numeric(pd.Series(cc[col].to_numpy(),index=rows.index),errors='coerce') if col in cc else np.nan
    rows['hourly_known_ts']=hourkeys
    rows['minute_known_ts']=np.where(cc.observed.fillna(False) if 'observed' in cc else False,dec,np.nan)
    rows['minute_valid']=cc.minute_valid.fillna(False).to_numpy(dtype=bool) if 'minute_valid' in cc else False
    rows['source_max_open_ts']=np.where(rows.minute_valid,dec-M,np.nan)
    rows['source_max_known_ts']=np.where(rows.minute_valid,dec,np.nan)
    rows['background_available']=rows.r6.notna()
    rows['residual_available']=rows.residual6.notna()
    rows['activity_available']=rows.quote_rvol.notna()&rows.count_rvol.notna()
    rows['utc_hour_sin']=np.sin(2*np.pi*((dec% D)/H)/24)
    rows['utc_hour_cos']=np.cos(2*np.pi*((dec% D)/H)/24)
    return rows

def clock_rows(symbol,contract,days,h,ctx,qtime):
    times=np.concatenate([int(pd.Timestamp(day,tz='UTC').timestamp()*1000)+np.arange(48,dtype=np.int64)*30*M for day in sorted(days)])
    out=pd.DataFrame({'decision_ts':times,'symbol':symbol,'contract':contract or ''})
    out['row_id']=[f'clock:{symbol}:{int(t)}' for t in times]
    out['eligible_decision']=True;out['quarantined']=times>=qtime if qtime is not None else False
    out=attach_context(out,h,ctx)
    out['side']=np.sign(out.r6).fillna(0).astype('int8')
    out['mapped']=contract is not None
    out['decision_valid']=out.mapped&out.minute_valid&~out.quarantined
    out['missing_reason']=np.select([~out.mapped,out.quarantined,~out.minute_valid,out.r6.isna(),out.residual6.isna(),out.quote_rvol.isna()|out.count_rvol.isna()],
        ['unmapped_perpetual','known_quarantine','missing_or_zero_trade_minute','insufficient_valid_direction_history','btc_self_or_insufficient_residual_history','insufficient_same_phase_activity_history'],default='none')
    for col in EVENT_FEATURES:out[col]=np.nan
    out['feature_known_ts']=out.decision_ts
    return out

def cohort_summary(frame,cohort,symbol):
    if frame.empty:return {'cohort':cohort,'symbol':symbol,'rows':0,'feature_nonnull':{k:0 for k in FEATURES}}
    applicable=EVENT_FEATURES if cohort=='event' else [k for k in FEATURES if k not in EVENT_FEATURES]
    return {'cohort':cohort,'symbol':symbol,'rows':len(frame),
            'feature_nonnull':{k:int(frame[k].notna().sum()) for k in FEATURES},
            'applicable_feature_fraction':{k:float(frame[k].notna().mean()) for k in applicable},
            'decision_valid':int(frame.decision_valid.sum()),
            'statuses':{str(k):int(v) for k,v in frame[('event_status' if cohort=='event' else 'missing_reason')].value_counts(dropna=False).items()}}

def build(selected=None):
    assert (ROOT/'data/READY.json').exists(),'Unified data version not ready'
    for sub in ['hourly','clock','events']: (OUT/sub).mkdir(parents=True,exist_ok=True)
    mapping=data_io.load_mapping();pools=data_io.load_daily_pools();quarantine=data_io.load_quarantine()
    days={s:set() for s in mapping}
    for row in pools:
        for p in row['pool']:days[p['symbol']].add(row['date'])
    registration=ROOT.parent/'feature-research-phase1/research_registration.json'
    dump(OUT/'build_registration.json',{'started_utc':datetime.now(timezone.utc).isoformat(),
        'protocol_sha256':sha(registration),'features_sha256':sha(ROOT/'features.py'),
        'builder_sha256':sha(ROOT/'build_features.py'),'data_manifest_sha256':sha(ROOT/'data/manifest.json'),
        'start':START,'end_exclusive':END,'outcomes_read':False,'backtests_executed':0,
        'technical_clarifications':['F3 rolling60m uses previous20days same minute-of-day phase','ATR requires valid previous closed15m close for TR','event measurement at t0_open+6min','clock full raw pool retained including unmapped/quarantined rows; flags govern comparisons']})
    btcraw=data_io.load_minutes('BTCUSDT',end_ms=END)
    btc=compute_hourly(btcraw,is_btc=True,asof_ms=END)
    del btcraw;gc.collect()
    records=[];coverage=[];monthly=[];legacy=[]
    old_path=ROOT.parent/'crypto-spot-kit/short-term-research/pullback-research-v2/universe-hours.parquet'
    old=pd.read_parquet(old_path,columns=['ts','symbol','residual_score','rvol','count_rvol'])
    pairs=list(sorted(mapping.items()))
    if selected is not None:pairs=[p for p in pairs if p[0] in selected or p[1] in selected]
    for i,(symbol,contract) in enumerate(pairs,1):
        if contract:
            raw=data_io.load_minutes(contract,end_ms=END)
            h=compute_hourly(raw,btc,is_btc=(contract=='BTCUSDT'),asof_ms=END)
            ctx=compute_minute_context(raw,asof_ms=END)
        else:
            raw=pd.DataFrame(columns=['ts','open','high','low','close','volume','quote_volume','trade_count','taker_buy_quote_volume'])
            h=compute_hourly(raw,btc);ctx=compute_minute_context(raw)
        q=quarantine.get(symbol,quarantine.get(contract,{}))
        qtime=q.get('known_ts') if isinstance(q,dict) else q
        if len(h):
            hs=h.reset_index(drop=True).copy();hs['symbol']=symbol;hs['contract']=contract
            hp=OUT/'hourly'/f'{symbol}.parquet';hs.to_parquet(hp,index=False)
            records.append({'kind':'hourly','symbol':symbol,'path':str(hp),'rows':len(hs),'sha256':sha(hp)})
        clock=clock_rows(symbol,contract,days[symbol],h,ctx,qtime)
        cp=OUT/'clock'/f'{symbol}.parquet';clock.to_parquet(cp,index=False)
        records.append({'kind':'clock','symbol':symbol,'path':str(cp),'rows':len(clock),'sha256':sha(cp)})
        coverage.append(cohort_summary(clock,'clock',symbol))
        ev=build_event_rows(raw,ctx,days[symbol],qtime,start_ms=START,end_ms=END,asof_ms=END)
        if len(ev):
            ev['symbol']=symbol;ev['contract']=contract
            ev['event_id']=symbol+':'+ev.event_id.astype(str)
            ev['row_id']='event:'+ev.event_id
            ev['event_window_valid']=ev.minute_valid.copy()
            ev=attach_context(ev,h,ctx)
            ev['minute_valid']=ev.minute_valid&ev.event_window_valid
            ev['decision_valid']=ev.event_status.eq('measured')&ev.eligible_decision.fillna(False).astype(bool)&~ev.quarantined.fillna(True).astype(bool)&ev.minute_valid
            ev['feature_known_ts']=ev.decision_ts
            ev['mapped']=True
        else:
            for col in ['symbol','contract','row_id','feature_known_ts','mapped','decision_valid','vol24','btc_r6','utc_hour_sin','utc_hour_cos']+FEATURES:
                if col not in ev:ev[col]=pd.Series(dtype='float64' if col in FEATURES else 'object')
        ep=OUT/'events'/f'{symbol}.parquet';ev.to_parquet(ep,index=False)
        records.append({'kind':'event','symbol':symbol,'path':str(ep),'rows':len(ev),'sha256':sha(ep)})
        coverage.append(cohort_summary(ev,'event',symbol))
        for cohort,frame in [('clock',clock),('event',ev)]:
            if frame.empty:continue
            month=pd.to_datetime(frame.decision_ts,unit='ms',utc=True).dt.strftime('%Y-%m')
            for name,g in frame.groupby(month):
                z=cohort_summary(g,cohort,symbol);z['month']=name;monthly.append(z)
        prev=old[old.symbol.eq(symbol)].copy()
        if len(prev):
            nh=h.reindex(prev.ts.to_numpy()).reset_index(drop=True)
            for col in ['residual6','quote_rvol','count_rvol','r6','efficiency6','concentration6','vol24']:
                prev['new_'+col]=nh[col].to_numpy()
            prev['contract']=contract;legacy.append(prev)
        dump(OUT/'progress.json',{'completed_symbols':i,'total_symbols':len(pairs),'symbol':symbol,'utc':datetime.now(timezone.utc).isoformat()})
        print(f'FEATURES {i}/{len(pairs)} {symbol} clock={len(clock)} events={len(ev)}',flush=True)
        del raw,h,ctx,clock,ev;gc.collect()
    matched=pd.concat(legacy,ignore_index=True)
    matched.to_parquet(OUT/'matched_legacy_hours.parquet',index=False)
    nonbtc=matched.contract.ne('BTCUSDT')
    oldstats={'exact_old_index_rows':len(matched),'non_btc_rows':int(nonbtc.sum()),
              'old_residual_available':int((nonbtc&matched.residual_score.notna()).sum()),
              'new_residual_available':int((nonbtc&matched.new_residual6.notna()).sum()),
              'old_quote_rvol_available':int(matched.rvol.notna().sum()),
              'new_quote_rvol_available':int(matched.new_quote_rvol.notna().sum()),
              'old_count_rvol_available':int(matched.count_rvol.notna().sum()),
              'new_count_rvol_available':int(matched.new_count_rvol.notna().sum()),
              'old_residual_available_but_new_missing':int((nonbtc&matched.residual_score.notna()&matched.new_residual6.isna()).sum()),
              'new_residual_gained':int((nonbtc&matched.residual_score.isna()&matched.new_residual6.notna()).sum())}
    dump(OUT/'legacy_coverage_comparison.json',oldstats)
    dump(OUT/'coverage_by_symbol.json',coverage);dump(OUT/'coverage_by_symbol_month.json',monthly)
    manifest={'completed_utc':datetime.now(timezone.utc).isoformat(),'records':records,
              'source_manifest_sha256':sha(ROOT/'data/manifest.json'),'features_sha256':sha(ROOT/'features.py'),
              'builder_sha256':sha(ROOT/'build_features.py'),'outcome_columns_created':False,
              'legacy_coverage_comparison':oldstats,'partial_symbols_run':selected}
    dump(OUT/'manifest.json',manifest)
    dump(OUT/'READY.json',{'ready':True,'manifest_sha256':sha(OUT/'manifest.json'),'partial':selected is not None,'utc':datetime.now(timezone.utc).isoformat()})
    print(json.dumps(oldstats,ensure_ascii=False),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--symbols',nargs='*');args=ap.parse_args()
    build(args.symbols)
