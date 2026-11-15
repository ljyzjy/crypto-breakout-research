"""Recover mark/funding data, apply 10x/20x risk proxies and score only complete paths."""
import concurrent.futures,hashlib,io,json,shutil,threading,time
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
WORK=ROOT/'work'/'point_in_time_universe33'/'risk';WORK.mkdir(parents=True,exist_ok=True)
M=60_000;MIN_FREE=1_900_000_000;BASE='https://data.binance.vision/data/futures/um/monthly/'
local=threading.local();FINGERPRINT=None
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def task(spec):
    kind,contract,month,times=spec
    name=f'{contract}-1m-{month}.zip' if kind=='markPriceKlines' else f'{contract}-fundingRate-{month}.zip'
    sub=f'{kind}/{contract}/1m/' if kind=='markPriceKlines' else f'{kind}/{contract}/';url=BASE+sub+name
    digest=hashlib.sha256((FINGERPRINT+'|'+kind+'|'+contract+'|'+month+'|'+','.join(map(str,times))).encode()).hexdigest()
    path=WORK/(digest+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        ch=session().get(url+'.CHECKSUM',timeout=(15,50))
        if ch.status_code==404:return {'kind':kind,'contract':contract,'month':month,'status':'checksum_404','rows':[]}
        ch.raise_for_status();sha=ch.text.strip().split()[0].lower();r=session().get(url,timeout=(15,100));r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('checksum_mismatch')
        d=pd.read_csv(io.BytesIO(r.content),compression='zip')
        cols=['open_time','open','high','low','close'] if kind=='markPriceKlines' else ['calc_time','funding_interval_hours','last_funding_rate']
        if not set(cols).issubset(d.columns):raise ValueError('source_columns')
        d=d[cols].apply(pd.to_numeric,errors='raise').rename(columns={'open_time':'ts','calc_time':'ts'})
        if not np.isfinite(d.to_numpy(float)).all() or d.ts.duplicated().any():raise ValueError('nonfinite_or_duplicate')
        lo=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)
        hi=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        if not d.ts.between(lo,hi-1).all():raise ValueError('outside_month')
        if kind=='markPriceKlines':
            if (d.ts%M!=0).any() or not (d[['open','high','low','close']]>0).all().all():raise ValueError('bad_mark')
            if (d.high<d[['open','low','close']].max(axis=1)).any() or (d.low>d[['open','high','close']].min(axis=1)).any():raise ValueError('bad_mark_ohlc')
            d=d[d.ts.isin(times)]
        elif (d.funding_interval_hours<=0).any():raise ValueError('bad_funding_interval')
        out={'kind':kind,'contract':contract,'month':month,'status':'verified','sha256':sha,'bytes':len(r.content),'rows':d.to_dict('records')}
        temp=path.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)
        return out
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:150]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'kind':kind,'contract':contract,'month':month,'status':'error','error':error,'rows':[]}
def funding_ok(rows,ts):
    if not rows:return False
    x=np.asarray([(r['ts'],r['funding_interval_hours']) for r in rows],float);x=x[np.argsort(x[:,0])]
    pos=np.searchsorted(x[:,0],ts,side='right');before=x[max(0,pos-1)];after=x[min(len(x)-1,pos)]
    allowance=max(before[1],after[1])*HOURS*1.5
    if pos==0:return x[0,0]-ts<=allowance
    if pos==len(x):return ts-x[-1,0]<=allowance
    return after[0]-before[0]<=allowance
HOURS=3_600_000
def settle(r,marks,funds,source_status):
    side=int(r.side);entry_ts=int(r.entry_ts);exit_ts=int(r.exit_ts);entry=float(r.entry_fill);qty=1/entry
    months={pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m') for ts in range(entry_ts//M*M,exit_ts//M*M+M,M)}
    for month in months:
        if source_status.get(('markPriceKlines',r.contract,month))!='verified':return {'risk_status':'missing_mark_archive'}
        if source_status.get(('fundingRate',r.contract,month))!='verified':return {'risk_status':'missing_funding_archive'}
    funding=0.;extremes=[];fund_events=[]
    for ts in range(entry_ts//M*M,exit_ts//M*M+M,M):
        mark=marks.get((r.contract,ts));month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
        fr=funds.get((r.contract,month),[])
        if mark is None:return {'risk_status':'missing_mark_minute'}
        if not funding_ok(fr,ts):return {'risk_status':'funding_coverage_uncertain'}
        extremes.append(float(mark['low'] if side==1 else mark['high']))
        for a in fr:
            ft=int(a['ts'])
            if ft//M*M!=ts or not entry_ts<=ft<=exit_ts:continue
            amount=side*qty*float(mark['open'])*float(a['last_funding_rate'])
            amount=max(0.,amount) if ft in (entry_ts,exit_ts) else amount
            funding+=amount;fund_events.append({'settlement_ts':ft,'mark_open':float(mark['open']),
                                               'rate':float(a['last_funding_rate']),'charge':amount})
    leverage=int(r.variant.rsplit('_',1)[1].rstrip('x'))
    liq=any(1/leverage-.0005-max(funding,0.)+side*qty*(x-entry)<=qty*x*(.005+.005) for x in extremes)
    exit_fill=float(r.exit_fill);exit_fee=qty*exit_fill*.0005
    net=side*qty*(exit_fill-entry)-.0005-exit_fee-funding
    return {'risk_status':'verified','funding':funding,'funding_events_json':json.dumps(fund_events,ensure_ascii=False),
            'liq_proxy':bool(liq),'entry_fee':.0005,'exit_fee':exit_fee,'net_per_unit_notional':net,
            'net_pct_notional':100*net}
def metrics(g):
    x=g.net_per_unit_notional.to_numpy(float);w=x[x>0];l=x[x<0]
    return {'events':len(x),'net_wins':len(w),'net_win_rate_pct':float(100*len(w)/len(x)) if len(x) else None,
            'average_net_pct_notional':float(100*x.mean()) if len(x) else None,
            'profit_factor':float(w.sum()/-l.sum()) if len(l) else None}
def main():
    global FINGERPRINT
    meta=json.loads((HERE/'动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    signal=pd.read_parquet(HERE/'动态池逐笔信号筛查.parquet');paths=pd.read_parquet(HERE/'动态池延迟市价路径.parquet')
    bad_input=bool(meta['archive_errors'] or meta['unexpected_event_count'] or meta['unverified_path_count'])
    if not len(paths):
        (HERE/'动态池单位筛查完整性.json').write_text(json.dumps({'complete':False,'reason':'no_paths','tape_incomplete':bad_input},ensure_ascii=False,indent=2),encoding='utf-8');return
    valid=paths[paths.status.eq('verified')].copy()
    d=valid.merge(signal[['observation_id','contract','side','source_year','decision_ts','quarter_end']],on='observation_id',validate='many_to_one')
    required={}
    for r in d.itertuples(index=False):
        for ts in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m');required.setdefault((r.contract,month),set()).add(ts)
    specs=[]
    for (contract,month),times in sorted(required.items()):
        specs.extend([('markPriceKlines',contract,month,sorted(times)),('fundingRate',contract,month,[])])
    # Each task key already contains the exact symbol/month and required mark
    # timestamps. Avoid invalidating unrelated source snapshots when a pending
    # path is later recovered; record the complete input hash separately.
    FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+(HERE/'逐笔执行冻结方案.json').read_bytes()).hexdigest()
    print('UNIVERSE33_RISK_TASKS',len(specs),'verified_paths',len(d),'tape_incomplete',bad_input,flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fs=[pool.submit(task,s) for s in specs]
        for f in concurrent.futures.as_completed(fs):
            results.append(f.result())
            if len(results)%20==0:print('UNIVERSE33_RISK',len(results),'/',len(specs),flush=True)
    marks={};funds={};source_status={}
    for rec in results:
        source_status[(rec['kind'],rec['contract'],rec['month'])]=rec['status']
        if rec['kind']=='markPriceKlines':
            for x in rec['rows']:marks[(rec['contract'],int(x['ts']))]=x
        else:funds[(rec['contract'],rec['month'])]=rec['rows']
    checked=[settle(r,marks,funds,source_status) for r in d.itertuples(index=False)]
    ledger=pd.concat([d.reset_index(drop=True),pd.DataFrame(checked)],axis=1)
    ledger.to_parquet(HERE/'动态池单位收益与风险.parquet',index=False)
    missing=ledger[~ledger.risk_status.eq('verified')];liqs=int(ledger.liq_proxy.fillna(False).sum()) if 'liq_proxy' in ledger else 0
    complete=not bad_input and not len(missing) and liqs==0
    quality={'complete':complete,'tape_incomplete':bad_input,'verified_tape_paths':len(d),'ledger_paths':len(ledger),
             'source_paths_sha256':hashlib.sha256((HERE/'动态池延迟市价路径.parquet').read_bytes()).hexdigest(),
             'risk_statuses':ledger.risk_status.value_counts().to_dict(),'liquidation_proxy_paths':liqs,
             'archive_statuses':pd.Series([r['status'] for r in results]).value_counts().to_dict(),
             'archive_failures':[{k:v for k,v in r.items() if k!='rows'} for r in results if r['status']!='verified'],
             'note':'Any unverified tape/risk path or liquidation proxy prevents a passing unit screen; not an account result.'}
    (HERE/'动态池单位筛查完整性.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=[{k:v for k,v in r.items() if k!='rows'} for r in results]
    (HERE/'动态池风险档案核验清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    if not complete:print('UNIVERSE33_RISK_INCOMPLETE',json.dumps(quality,ensure_ascii=False),flush=True);return
    print('CROSS44_RISK_COMPLETE',json.dumps(quality,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
