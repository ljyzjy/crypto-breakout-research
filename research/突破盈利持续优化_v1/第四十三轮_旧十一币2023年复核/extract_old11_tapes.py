"""Replay prefiltered 2023 first-touch candidates with source-mismatch safeguards."""
import concurrent.futures,hashlib,io,json,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;ORIG=P/'第三十三轮_动态池逐笔执行'
sys.path.insert(0,str(ORIG));import extract_dynamic_tapes as engine
SOURCE=H/'2023双币过滤潜在触价.parquet';PLAN=H/'冻结研究方案.md';NORM=ROOT/'work'/'breakout_2023_11'/'normalized'
WORK=ROOT/'work'/'old11_2023_dual'/'tape';WORK.mkdir(parents=True,exist_ok=True);M=60_000
FP=hashlib.sha256(Path(__file__).read_bytes()+(ORIG/'extract_dynamic_tapes.py').read_bytes()+
  (ORIG/'tape_decision.py').read_bytes()+(ORIG/'leveraged_paths.py').read_bytes()+PLAN.read_bytes()+SOURCE.read_bytes()).hexdigest()
def task(spec):
    contract,day,needs_next,events=spec
    key=hashlib.sha256((FP+'|'+contract+'|'+day+'|'+str(needs_next)+'|'+'|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest();path=WORK/(key+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<800*1024**2:time.sleep(3)
        if shutil.disk_usage(ROOT).free<1_900_000_000:raise RuntimeError('disk_reserve')
        body,bar_meta=engine.archive('klines',contract,day);bars=engine.minute_bars(body,day);del body
        local=pd.read_parquet(NORM/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        mismatch=set()
        for e in events:
            times=np.arange(int(e['quarter_start']),int(e['trigger_minute'])+M,M,dtype=np.int64)
            x=local.reindex(times);y=bars.reindex(times);cols=['open','high','low','close']
            if not np.isfinite(x[cols].to_numpy(float)).all() or not np.isfinite(y[cols].to_numpy(float)).all() or not np.allclose(x[cols],y[cols],rtol=1e-9,atol=1e-12):
                mismatch.add(e['observation_id'])
        archives=[bar_meta];dates=[day]
        if needs_next:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        blocks={e['observation_id']:[] for e in events}
        for date in dates:
            body,meta=engine.archive('aggTrades',contract,date);archives.append(meta)
            cols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
            for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=cols,dtype={'is_buyer_maker':str},chunksize=150_000):
                times=chunk.transact_time.to_numpy(np.int64)
                for e in events:
                    part=chunk.loc[(times>=int(e['trigger_minute']))&(times<int(e['quarter_end'])+60_000)]
                    if len(part):blocks[e['observation_id']].append(part)
            del body
        rows=[]
        for e in events:
            obs=e['observation_id']
            if e['market_prior_status']!='allowed':rows.append({'observation_id':obs,'status':'market_data_unknown'});continue
            if obs in mismatch:rows.append({'observation_id':obs,'status':'daily_monthly_ohlc_mismatch'});continue
            if not blocks[obs]:rows.append({'observation_id':obs,'status':'missing_event_tape'});continue
            ticks=pd.concat(blocks[obs],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            rows.append({'observation_id':obs,**engine.decide(e,ticks,bars)})
        out={'contract':contract,'day':day,'needs_next':needs_next,'status':'verified','archives':archives,'rows':rows}
        if shutil.disk_usage(ROOT).free<1_900_000_000:raise RuntimeError('disk_reserve')
        tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path);return out
      except Exception as e:
        error=type(e).__name__+':'+str(e)[:140]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs_next,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error'} for e in events]}
def main():
    a=json.loads((H/'2023候选特征独立核验.json').read_text(encoding='utf-8'))
    b=json.loads((H/'2023日小时排名独立核验.json').read_text(encoding='utf-8'))
    c=json.loads((H/'2023双币过滤候选质量.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and b['all_checks_pass'];d=pd.read_parquet(SOURCE)
    assert len(d)==a['all_candidate_gates_checked']==c['post_hour_and_market_candidates']
    tasks=[(sym,day,bool(needs),g.to_dict('records')) for (sym,day,needs),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]));print('OLD11_2023_TAPE_TASKS',len(tasks),'candidates',len(d),flush=True);result=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for f in concurrent.futures.as_completed([pool.submit(task,t) for t in tasks]):
            result.append(f.result())
            if len(result)%10==0:print('OLD11_2023_TAPES',len(result),'/',len(tasks),flush=True)
    rows=[];paths=[];archives=[]
    for r in result:
        archives.append({k:v for k,v in r.items() if k!='rows'})
        for row in r['rows']:
            p=row.pop('paths',{});pre=row.pop('prechecks',{})
            for variant,value in p.items():paths.append({'observation_id':row['observation_id'],'variant':variant,**value})
            rows.append({**row,'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
    signal=pd.DataFrame(rows);assert signal.observation_id.is_unique and len(signal)==len(d)
    signal=signal.merge(d,on='observation_id',validate='one_to_one',suffixes=('','_candidate'))
    signal.to_parquet(H/'动态池逐笔信号筛查.parquet',index=False)
    paths=pd.DataFrame(paths)
    if len(paths):assert not paths.duplicated(['observation_id','variant']).any()
    paths.to_parquet(H/'动态池延迟市价路径.parquet',index=False)
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    meta={'candidate_events':len(d),'daily_tasks':len(tasks),'event_statuses':signal.status.value_counts().to_dict(),
          'unexpected_event_count':int((~signal.status.isin(benign)).sum()),'variant_paths':len(paths),
          'unverified_path_count':int((~paths.status.eq('verified')).sum()) if len(paths) else 0,
          'archive_errors':[r for r in archives if r['status']!='verified'],'archives':archives,
          'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
          'note':'Unknown archives, daily/monthly disagreements, trade discrepancies and market missingness remain explicit.'}
    (H/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copyfile(PLAN,H/'逐笔执行冻结方案.json');shutil.copyfile(ORIG/'不完整数据敏感性规则.json',H/'不完整数据敏感性规则.json')
    print('OLD11_2023_TAPES_COMPLETE',json.dumps({k:v for k,v in meta.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
