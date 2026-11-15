"""Stream official trades for paired one-second entry, preserving all unknowns."""
import hashlib,json,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import entry_1s
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;M=60_000
R48=P/'第四十八轮_固定一倍风险止盈';sys.path.insert(0,str(R48));import run_1r_2023 as old23,run_1r_later as oldlater
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as direct
sys.path.insert(0,str(P/'第三十三轮_动态池逐笔执行'));import extract_dynamic_tapes as source
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fingerprint(year):
    return hashlib.sha256(Path(__file__).read_bytes()+(H/'冻结研究方案.md').read_bytes()+(H/f'{year}输入冻结哈希.json').read_bytes()+
                          (H/'entry_1s.py').read_bytes()+(P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest()
def key_for(fp,spec):
    sym,day,needs,events=spec
    return hashlib.sha256((fp+'|'+sym+'|'+day+'|'+str(needs)+'|'+'|'.join(sorted(x['observation_id'] for x in events))).encode()).hexdigest()
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def task(year,fp,spec,index,refs,work):
    contract,day,needs,events=spec;file=work/(key_for(fp,spec)+'.json')
    if file.exists():return json.loads(file.read_text(encoding='utf-8'))
    error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<500*1024**2:
            if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
            time.sleep(3)
        guard();body,bar=source.archive('klines',contract,day);bars=source.minute_bars(body,day);del body
        folder={'2023':'breakout_2023_11','2024':'breakout_2024_11','2026':'breakout_forward_2026'}[year]
        norm=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{contract}_klines.parquet',columns=['ts','open','high','low','close']).set_index('ts')
        statuses={};usable=[]
        for e in events:
            obs=e['observation_id'];prior=index.get(obs)
            if not prior:statuses[obs]='old_archive_provenance_missing';continue
            if prior['daily_sha256']!=bar['sha256']:statuses[obs]='official_day_source_changed';continue
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
                lev=int(old['variant'].rsplit('_',1)[1].rstrip('x'));paths[f'one_second_2r_{lev}x']=entry_1s.decide(e,old,tape)
            rows.append({'observation_id':obs,'status':'qualified','paths':paths})
        result={'contract':contract,'day':day,'needs_next':needs,'status':'verified','archives':archives,'rows':rows}
        guard();tmp=file.with_suffix('.partial');tmp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(file);return result
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:150]
        if 'headroom' in error or 'stream_cap' in error or 'window_exceeds' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'contract':contract,'day':day,'needs_next':needs,'status':'error','error':error,
            'rows':[{'observation_id':e['observation_id'],'status':'archive_error'} for e in events]}
def main(year):
    I=H/f'{year}冻结输入';f=json.loads((H/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(H/'冻结研究方案.md')==f['plan_sha256'] and sha(H/'entry_1s.py')==f['code_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    test=json.loads((H/'一秒入场合成核验.json').read_text(encoding='utf-8'));assert test['all_checks_pass'] and test['code_sha256']==sha(H/'entry_1s.py')
    pub=P/'第四十七轮_一次重新突破确认';real=json.loads((pub/'无落盘逐笔读取真实样本核验.json').read_text(encoding='utf-8'))
    assert real['all_checks_pass'] and real['stream_code_sha256']==sha(pub/'public_tape_stream.py')
    fp=fingerprint(year);work=ROOT/'work'/f'entry1s51_{year}'/'tape';work.mkdir(parents=True,exist_ok=True)
    d=pd.read_parquet(I/'qualified_entries.parquet');refs=pd.read_parquet(I/'reference_2r_paths.parquet')
    index=old23.provenance(d,refs) if year=='2023' else oldlater.provenance(year,d,refs)
    sizes={}
    for obs,v in index.items():
        if 'bytes' in v:sizes[obs]=v['bytes']
        else:
            z=json.loads(Path(v['checkpoint']).read_text(encoding='utf-8'))
            sizes[obs]=sum(int(x.get('bytes',0)) for x in z['archives'] if x['kind']=='aggTrades') or 10**12
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda x:(max(sizes.get(e['observation_id'],10**12) for e in x[3]),x[1],x[0]));done=0;errors=[]
    print('ENTRY51_TASKS',year,len(tasks),'events',len(d),'provenance',len(index),flush=True)
    for spec in tasks:
        if shutil.disk_usage(ROOT).free<2_200_000_000:break
        z=task(year,fp,spec,index,refs,work)
        if z['status']!='verified':
            errors.append({'contract':z['contract'],'day':z['day'],'error':z.get('error')})
            if 'headroom' in z.get('error',''):break
        done+=1
        if done%5==0:print('ENTRY51_TAPES',year,done,'/',len(tasks),'errors',len(errors),flush=True)
    out={'year':year,'processed_tasks':done,'total_tasks':len(tasks),'errors':errors,'fingerprint':fp,
         'free_bytes':shutil.disk_usage(ROOT).free,'note':'Size orders retrieval only; unresolved paths remain unknown.'}
    (H/f'{year}一秒入场逐笔进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENTRY51_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
