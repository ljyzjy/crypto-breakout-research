"""Re-read all known fixed-pool candidates with SHA-verified public tapes."""
import hashlib,json,math,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import one_second_observation as new
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;R48=P/'第四十八轮_固定一倍风险止盈';RET=P/'第四十七轮_一次重新突破确认';ORIG=P/'第三十三轮_动态池逐笔执行'
sys.path.insert(0,str(R48));import public_range
sys.path.insert(0,str(ORIG));import extract_dynamic_tapes as source,tape_decision as old_engine
M=60000
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
def fingerprint(year):
    files=[Path(__file__),H/'冻结研究方案.md',H/'one_second_observation.py',H/f'{year}输入冻结哈希.json',
           H/f'{year}已知候选逐笔来源.json',R48/'public_range.py',RET/'public_tape_stream.py',ORIG/'tape_decision.py',ORIG/'leveraged_paths.py']
    return hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()
def key(fp,spec):
    sym,day,n,events=spec
    return hashlib.sha256((fp+'|'+sym+'|'+day+'|'+str(n)+'|'+'|'.join(sorted(x['observation_id'] for x in events))).encode()).hexdigest()
def inputs(year):
    I=H/f'{year}冻结输入';f=json.loads((H/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
    assert f['plan_sha256']==sha(H/'冻结研究方案.md') and f['decision_code_sha256']==sha(H/'one_second_observation.py')
    assert all(sha(I/n)==v for n,v in f['input_sha256'].items())
    test=json.loads((H/'一秒观察合成时序核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==sha(H/'one_second_observation.py') and test['plan_sha256']==sha(H/'冻结研究方案.md')
    comparison=json.loads((H/'原方案来源比较合成核验.json').read_text(encoding='utf-8'))
    assert comparison['all_checks_pass'] and comparison['runner_sha256']==sha(Path(__file__)) and comparison['plan_sha256']==sha(H/'冻结研究方案.md')
    verified=json.loads((R48/'分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert verified['all_checks_pass'] and verified['range_code_sha256']==sha(R48/'public_range.py') and verified['stream_code_sha256']==sha(RET/'public_tape_stream.py')
    proof=json.loads((H/f'{year}已知候选逐笔来源.json').read_text(encoding='utf-8'))
    assert proof['input_manifest_sha256']==sha(H/f'{year}输入冻结哈希.json')
    return pd.read_parquet(I/'candidates.parquet'),pd.read_parquet(I/'baseline_signal.parquet').set_index('observation_id'),pd.read_parquet(I/'baseline_paths.parquet'),proof['events']
def compare_baseline(obs,got,ref,paths):
    if got['status']!=ref['status']:return False
    for name in ('side','decision_ts','signal_close','entry_exec_ts','raw_entry_5s','five_count','buy_notional','sell_notional','five_imbalance','stop_price','level'):
        if name not in got:continue
        old=ref.get(name)
        if pd.isna(old) or pd.isna(got[name]):
            if pd.isna(old) and pd.isna(got[name]):continue
            return False
        if name in ('side','five_count') or name.endswith('_ts'):
            if int(got[name])!=int(old):return False
        elif not near(got[name],old):return False
    if got['status'] in ('qualified','known_risk_rejected'):
        for lev in (10,20):
            if got['prechecks'][str(lev)]!=ref[f'precheck_{lev}x']:return False
    if got['status']=='qualified':
        p=paths[paths.observation_id.eq(obs)]
        if set(got['paths'])!=set(p.variant):return False
        for row in p.to_dict('records'):
            v=got['paths'][row['variant']]
            if v['status']!=row['status']:return False
            if v['status']=='verified':
                for name in ('entry_ts','entry_raw','entry_fill','exit_signal_ts','exit_ts','exit_raw','exit_fill','initial_stop'):
                    if name.endswith('_ts'):
                        if int(v[name])!=int(row[name]):return False
                    elif not near(v[name],row[name]):return False
                if v['reason']!=row['reason']:return False
    return True
def task(year,fp,spec,baseline,paths,proof,work):
    symbol,day,needs,events=spec;dest=work/(key(fp,spec)+'.json')
    if dest.exists():return json.loads(dest.read_text(encoding='utf-8'))
    for e in events:
        rec=proof[e['observation_id']]
        if 'checkpoint' in rec:assert sha(Path(rec['checkpoint']))==rec['checkpoint_sha256']
    error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<500*1024**2:guard();time.sleep(3)
        guard();body,bar=source.archive('klines',symbol,day);bars=source.minute_bars(body,day);del body
        minute_sources=json.loads((H/f'{year}冻结输入'/'minute_sources.json').read_text(encoding='utf-8'))['sources']
        item=minute_sources[f'{symbol}_klines.parquet' if year=='2023' else f'{year}_{symbol}'];normpath=Path(item['path'])
        assert sha(normpath)==item['sha256'];norm=pd.read_parquet(normpath,columns=['ts','open','high','low','close']).set_index('ts')
        bad={};good=[]
        for e in events:
            obs=e['observation_id'];rec=proof[obs]
            if rec['daily_sha256']!=bar['sha256']:bad[obs]='official_day_source_changed';continue
            ts=range(int(e['quarter_start']),int(e['trigger_minute'])+M,M);cols=['open','high','low','close']
            x=norm.reindex(ts)[cols].to_numpy(float);y=bars.reindex(ts)[cols].to_numpy(float)
            if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.allclose(x,y,rtol=1e-9,atol=1e-12):bad[obs]='daily_monthly_ohlc_mismatch';continue
            good.append(e)
        dates=[day];archives=[bar];blocks={e['observation_id']:[] for e in good}
        if needs:dates.append((pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        for date in dates:
            if not good:break
            windows={e['observation_id']:(int(e['trigger_minute']),int(e['quarter_end'])+M) for e in good}
            got,meta=public_range.fetch(symbol,date,windows,guard);archives.append(meta)
            for e in good:
                obs=e['observation_id'];expected=proof[obs]['agg_archives'].get(date)
                if not expected or meta['sha256']!=expected['sha256'] or meta['bytes']!=expected['bytes']:bad[obs]='official_agg_source_changed'
                else:blocks[obs].extend(got[obs])
        rows=[]
        for e in events:
            obs=e['observation_id']
            if obs in bad:rows.append({'observation_id':obs,'status':bad[obs]});continue
            if not blocks[obs]:rows.append({'observation_id':obs,'status':'missing_event_tape'});continue
            tape=pd.concat(blocks[obs],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
            old=old_engine.decide(e,tape,bars)
            if not compare_baseline(obs,old,baseline.loc[obs],paths):rows.append({'observation_id':obs,'status':'baseline_replay_disagreement'});continue
            row=new.decide(e,tape,bars);rows.append({'observation_id':obs,**row})
        z={'contract':symbol,'day':day,'needs_next':needs,'status':'verified','archives':archives,'rows':rows};guard()
        temp=dest.with_suffix('.partial');temp.write_text(json.dumps(z,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(dest);return z
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:150]
        if 'headroom' in error or 'stream_cap' in error or 'window_exceeds' in error:break
        if attempt<2:time.sleep(attempt+1)
    return {'status':'error','error':error,'contract':symbol,'day':day}
def main(year):
    cand,baseline,paths,proof=inputs(year);d=cand[cand.observation_id.isin(proof)].copy();fp=fingerprint(year)
    work=ROOT/'work'/f'oneobs62_{year}'/'tape';work.mkdir(parents=True,exist_ok=True)
    tasks=[(s,day,bool(n),g.to_dict('records')) for (s,day,n),g in d.groupby(['contract','day','needs_next'])]
    tasks.sort(key=lambda z:(max(sum(a['bytes'] for a in proof[e['observation_id']]['agg_archives'].values()) for e in z[3]),z[1],z[0]))
    done=0;errors=[];print('OBS62_TASKS',year,len(tasks),'known_events',len(d),'original_unknown',len(cand)-len(d),flush=True)
    for spec in tasks:
        if shutil.disk_usage(ROOT).free<2_200_000_000:break
        z=task(year,fp,spec,baseline,paths,proof,work)
        if z['status']!='verified':
            errors.append({'contract':z['contract'],'day':z['day'],'error':z['error']})
            if 'headroom' in z['error']:break
        done+=1
        if done%5==0:print('OBS62_PROGRESS',year,done,'/',len(tasks),'errors',len(errors),flush=True)
    out={'year':year,'processed_groups':done,'total_groups':len(tasks),'errors':errors,'fingerprint':fp,
         'original_unknown':len(cand)-len(d),'note':'All baseline-known candidates considered; unprocessed data remain unknown.'}
    (H/f'{year}一秒观察逐笔进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
