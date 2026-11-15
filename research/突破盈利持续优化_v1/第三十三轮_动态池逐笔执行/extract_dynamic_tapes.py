"""Checkpointed official daily 1m/tape retrieval and 10x/20x delayed paths."""
import ast,concurrent.futures,hashlib,io,json,shutil,threading,time
from pathlib import Path
import numpy as np,pandas as pd,requests
from tape_decision import decide
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent
SOURCE=PARENT/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet'
PLAN=HERE/'逐笔执行冻结方案.json';WORK=ROOT/'work'/'point_in_time_universe33'/'tape';WORK.mkdir(parents=True,exist_ok=True)
M=60_000;MIN_FREE=1_900_000_000;BASE='https://data.binance.vision/data/futures/um/daily/'
local=threading.local();FINGERPRINT=None
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def session():
    if not hasattr(local,'s'):local.s=requests.Session()
    return local.s
def archive(kind,symbol,day):
    if kind=='klines':path=f'klines/{symbol}/1m/{symbol}-1m-{day}.zip'
    else:path=f'aggTrades/{symbol}/{symbol}-aggTrades-{day}.zip'
    url=BASE+path;check=session().get(url+'.CHECKSUM',timeout=(15,50));check.raise_for_status()
    sha=check.text.strip().split()[0].lower();r=session().get(url,timeout=(15,120));r.raise_for_status()
    if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('checksum_mismatch')
    return r.content,{'kind':kind,'day':day,'sha256':sha,'bytes':len(r.content)}
def minute_bars(body,day):
    d=pd.read_csv(io.BytesIO(body),compression='zip')
    if not {'open_time','open','high','low','close'}.issubset(d.columns):raise ValueError('minute_columns')
    d=d[['open_time','open','high','low','close']].apply(pd.to_numeric,errors='raise')
    if d.open_time.duplicated().any() or (d.open_time%M!=0).any():raise ValueError('minute_times')
    lo=int(pd.Timestamp(day,tz='UTC').timestamp()*1000)
    if not d.open_time.between(lo,lo+86_400_000-1).all():raise ValueError('minute_day')
    return d.set_index('open_time')
def task(spec):
    contract,day,needs_next,events=spec
    digest=hashlib.sha256((FINGERPRINT+'|'+contract+'|'+day+'|'+str(needs_next)+'|'+
            '|'.join(sorted(e['observation_id'] for e in events))).encode()).hexdigest();path=WORK/(digest+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    error='unknown'
    for attempt in range(3):
      try:
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        body,bar_meta=archive('klines',contract,day);bars=minute_bars(body,day);del body
        dates=[day]
        if needs_next:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        collected={e['observation_id']:[] for e in events};archives=[bar_meta]
        for which in dates:
            body,meta=archive('aggTrades',contract,which);archives.append(meta)
            cols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
            for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=cols,dtype={'is_buyer_maker':str},chunksize=150_000):
                times=chunk.transact_time.to_numpy(np.int64)
                for e in events:
                    mask=(times>=int(e['trigger_minute']))&(times<int(e['quarter_end'])+60_000)
                    part=chunk.loc[mask]
                    if len(part):collected[e['observation_id']].append(part)
            del body
        rows=[]
        for e in events:
            parts=collected[e['observation_id']]
            if not parts:rows.append({'observation_id':e['observation_id'],'status':'missing_event_tape'});continue
            ticks=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            outcome=decide(e,ticks,bars);rows.append({'observation_id':e['observation_id'],**outcome})
        result={'contract':contract,'day':day,'needs_next':needs_next,'status':'verified','archives':archives,'rows':rows}
        if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError('disk_reserve')
        temp=path.with_suffix('.partial');temp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)
        return result
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:160]
        if 'disk_reserve' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs_next,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error'} for e in events]}
def main():
    global FINGERPRINT
    audit=json.loads((PARENT/'第三十二轮_历史动态池分钟信号'/'动态分钟候选独立核验.json').read_text(encoding='utf-8'))
    # Reuse checkpoints from the original four-worker launch after increasing
    # concurrency only; verify all data/decision code and inputs are unchanged.
    tree=ast.parse(Path(__file__).read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('archive','minute_bars','task')]
    logic=ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False).encode()
    signature=hashlib.sha256(logic+(HERE/'tape_decision.py').read_bytes()+(HERE/'leveraged_paths.py').read_bytes()+
                             PLAN.read_bytes()+SOURCE.read_bytes()).hexdigest()
    assert signature=='6c8dce8231509bf4ef9562d304b497d1f10df74b2bfaad814878b0224675be3d'
    assert M==60_000 and MIN_FREE==1_900_000_000 and BASE=='https://data.binance.vision/data/futures/um/daily/'
    FINGERPRINT='38a1da4b58ea2bb538a522387497125aea3ddd88f0545c7beab90c83f2aa9286'
    d=pd.read_parquet(SOURCE);assert d.observation_id.is_unique and len(d)==audit['all_output_candidates_checked']
    d['needs_next']=(d.quarter_end+60_000-1)//86_400_000>d.trigger_minute//86_400_000
    tasks=[(contract,day,bool(nextday),g.to_dict('records')) for (contract,day,nextday),g in d.groupby(['contract','day','needs_next'])]
    # Prioritize the predetermined training interval; this changes retrieval
    # order only and preserves every task and the original checkpoint keys.
    tasks.sort(key=lambda x:(0 if '2024-01-01'<=x[1]<'2024-05-01' else 1,x[1],x[0],x[2]))
    print('UNIVERSE33_TAPE_TASKS',len(tasks),'events',len(d),'cross_utc',int(d.needs_next.sum()),flush=True);results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(task,x) for x in tasks]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if len(results)%20==0:print('UNIVERSE33_TAPES',len(results),'/',len(tasks),flush=True)
    rows=[];paths=[];archives=[]
    for result in results:
        archives.append({k:v for k,v in result.items() if k!='rows'})
        for row in result['rows']:
            p=row.pop('paths',{});pre=row.pop('prechecks',{})
            for variant,value in p.items():paths.append({'observation_id':row['observation_id'],'variant':variant,**value})
            rows.append({**row,'precheck_10x':pre.get('10'),'precheck_20x':pre.get('20')})
    decision=pd.DataFrame(rows);assert len(decision)==len(d) and decision.observation_id.is_unique
    decision=decision.merge(d,on='observation_id',validate='one_to_one',suffixes=('','_candidate'))
    decision.to_parquet(HERE/'动态池逐笔信号筛查.parquet',index=False)
    path_df=pd.DataFrame(paths)
    if len(path_df):assert not path_df.duplicated(['observation_id','variant']).any()
    path_df.to_parquet(HERE/'动态池延迟市价路径.parquet',index=False)
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
    status=decision.status.value_counts().to_dict();unexpected=decision[~decision.status.isin(benign)]
    failed_paths=path_df[~path_df.status.eq('verified')] if len(path_df) else path_df
    meta={'candidate_events':len(d),'daily_tasks':len(tasks),'cross_utc_events':int(d.needs_next.sum()),
          'event_statuses':status,'unexpected_event_count':len(unexpected),'variant_paths':len(path_df),
          'path_statuses':path_df.status.value_counts().to_dict() if len(path_df) else {},'unverified_path_count':len(failed_paths),
          'archive_errors':[x for x in archives if x['status']!='verified'],'archives':archives,
          'candidate_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),
          'note':'Unverified event/path is not silently omitted. Unit PnL still requires historical marks and funding.'}
    (HERE/'动态池逐笔提取质量.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_TAPES_COMPLETE',json.dumps({k:v for k,v in meta.items() if k!='archives'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
