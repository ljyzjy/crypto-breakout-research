"""Re-fetch frozen 2023 entry tapes and calculate paired 1R exits."""
import hashlib,json,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;I=H/'2023冻结输入'
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as direct
sys.path.insert(0,str(P/'第三十三轮_动态池逐笔执行'));import extract_dynamic_tapes as source
import exit_1r
WORK=ROOT/'work'/'exit1r48_2023'/'tape';WORK.mkdir(parents=True,exist_ok=True);M=60_000
FP=hashlib.sha256(Path(__file__).read_bytes()+(H/'冻结研究方案.md').read_bytes()+(H/'2023输入冻结哈希.json').read_bytes()+
                  (H/'exit_1r.py').read_bytes()+(P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def key_for(spec):
    symbol,day,needs,events=spec
    return hashlib.sha256((FP+'|'+symbol+'|'+day+'|'+str(needs)+'|'+'|'.join(sorted(x['observation_id'] for x in events))).encode()).hexdigest()
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def provenance(events,refs):
    needed={e['observation_id']:e['entry_origin'] for e in events.to_dict('records')};index={}
    roots=[('original',ROOT/'work'/'old11_2023_dual'/'tape'),('original',ROOT/'work'/'old11_2023_dual'/'stream_tape'),
           ('retest',ROOT/'work'/'retest47_2023'/'tape')]
    for origin,folder in roots:
      for f in sorted(folder.glob('*.json')):
        z=json.loads(f.read_text(encoding='utf-8'))
        if z.get('status')!='verified':continue
        for row in z['rows']:
          obs=row['observation_id']
          if needed.get(obs)!=origin:continue
          assert row['status']=='qualified';expected=refs[refs.observation_id.eq(obs)]
          for old in expected.to_dict('records'):
            variant=old['variant'];cp=row.get('paths',{}).get(variant);assert cp is not None and cp['status']==old['status']
            if cp['status']=='verified':
                for k in ('entry_ts','entry_raw','entry_fill','exit_signal_ts','exit_ts','exit_raw','exit_fill','initial_stop'):
                    assert np.isclose(cp[k],old[k],rtol=1e-11,atol=1e-12),(obs,variant,k)
                assert cp['reason']==old['reason']
          daily=next(x for x in z['archives'] if x['kind']=='klines' and x['day']==z['day'])
          aggs={x['day']:x['sha256'] for x in z['archives'] if x['kind']=='aggTrades'}
          rec={'daily_sha256':daily['sha256'],'agg_sha256':aggs,'checkpoint':str(f)}
          if obs in index:assert index[obs]['daily_sha256']==rec['daily_sha256'] and index[obs]['agg_sha256']==aggs
          else:index[obs]=rec
    return index
def task(spec,index,refs):
    contract,day,needs,events=spec;file=WORK/(key_for(spec)+'.json')
    if file.exists():return json.loads(file.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<500*1024**2:
            if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
            time.sleep(3)
        guard();body,bar=source.archive('klines',contract,day);bars=source.minute_bars(body,day);del body
        norm=pd.read_parquet(ROOT/'work'/'breakout_2023_11'/'normalized'/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        statuses={};usable=[]
        for e in events:
            obs=e['observation_id'];old=index.get(obs)
            if not old:statuses[obs]='old_archive_provenance_missing';continue
            if old['daily_sha256']!=bar['sha256']:statuses[obs]='official_day_source_changed';continue
            times=range(int(e['quarter_start']),int(e['trigger_minute'])+M,M);cols=['open','high','low','close']
            a=norm.reindex(times)[cols].to_numpy(float);b=bars.reindex(times)[cols].to_numpy(float)
            if not np.isfinite(a).all() or not np.isfinite(b).all() or not np.allclose(a,b,rtol=1e-9,atol=1e-12):statuses[obs]='daily_monthly_ohlc_mismatch';continue
            usable.append(e)
        dates=[day];archives=[bar];blocks={e['observation_id']:[] for e in usable}
        if needs:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        for date in dates:
            if not usable:break
            windows={e['observation_id']:(int(e['trigger_minute']),int(e['quarter_end'])+60_000) for e in usable}
            got,meta=direct.fetch(contract,date,windows,guard);archives.append(meta)
            for e in usable:
                obs=e['observation_id']
                if index[obs]['agg_sha256'].get(date)!=meta['sha256']:statuses[obs]='official_agg_source_changed'
                else:blocks[obs].extend(got[obs])
        rows=[]
        for e in events:
            obs=e['observation_id']
            if obs in statuses:rows.append({'observation_id':obs,'status':statuses[obs]});continue
            if not blocks[obs]:rows.append({'observation_id':obs,'status':'missing_event_tape'});continue
            tape=pd.concat(blocks[obs],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort');paths={}
            for old in refs[refs.observation_id.eq(obs)].to_dict('records'):
                lev=int(old['variant'].rsplit('_',1)[1].rstrip('x'));paths[f'normal_1r_{lev}x']=exit_1r.decide(e,old,tape)
            rows.append({'observation_id':obs,'status':'qualified','paths':paths})
        result={'contract':contract,'day':day,'needs_next':needs,'status':'verified','archives':archives,'rows':rows}
        guard();tmp=file.with_suffix('.partial');tmp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(file);return result
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:150]
        if 'headroom' in error or 'stream_cap' in error or 'window_exceeds' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error'} for e in events]}
def main():
    f=json.loads((H/'2023输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    test=json.loads((H/'一倍止盈合成核验.json').read_text(encoding='utf-8'));assert test['all_checks_pass'] and test['code_sha256']==sha(H/'exit_1r.py')
    pub=P/'第四十七轮_一次重新突破确认';real=json.loads((pub/'无落盘逐笔读取真实样本核验.json').read_text(encoding='utf-8'))
    assert real['all_checks_pass'] and real['stream_code_sha256']==sha(pub/'public_tape_stream.py')
    d=pd.read_parquet(I/'qualified_entries.parquet');refs=pd.read_parquet(I/'reference_2r_paths.parquet');assert d.observation_id.is_unique
    index=provenance(d,refs);tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(x[1],x[0]));done=0;errors=[]
    print('EXIT1R48_2023_TASKS',len(tasks),'events',len(d),'provenance',len(index),flush=True)
    for spec in tasks:
        if shutil.disk_usage(ROOT).free<2_200_000_000:break
        z=task(spec,index,refs)
        if z['status']!='verified':
            errors.append({'contract':z['contract'],'day':z['day'],'error':z.get('error')})
            if 'headroom' in z.get('error',''):break
        done+=1
        if done%5==0:print('EXIT1R48_2023_TAPES',done,'/',len(tasks),'errors',len(errors),flush=True)
    out={'processed_tasks':done,'total_tasks':len(tasks),'errors':errors,'fingerprint':FP,
         'free_bytes':shutil.disk_usage(ROOT).free,'note':'Unresolved 1R paths remain unknown; all entries are identical to 2R.'}
    (H/'2023一倍止盈逐笔进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_2023_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
