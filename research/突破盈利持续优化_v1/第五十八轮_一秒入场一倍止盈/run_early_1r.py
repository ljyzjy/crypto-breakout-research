"""Read the same SHA-verified public tapes to replay the frozen 1s/1R paths."""
import hashlib,json,shutil,sys,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import early_1r
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
FAST=P/'第五十一轮_缩短市价入场延迟';R48=P/'第四十八轮_固定一倍风险止盈';RET=P/'第四十七轮_一次重新突破确认'
sys.path.insert(0,str(R48));import public_range
sys.path.insert(0,str(FAST));import run_entry_1s as previous
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def fingerprint(year):
    pieces=[H/'冻结研究方案.md',H/'early_1r.py',Path(__file__),H/f'{year}输入冻结哈希.json',R48/'public_range.py',RET/'public_tape_stream.py']
    return hashlib.sha256(b''.join(p.read_bytes() for p in pieces)).hexdigest()
def key(fp,spec,oldsha):
    sym,day,needs,events=spec
    return hashlib.sha256((fp+'|'+sym+'|'+day+'|'+str(needs)+'|'+'|'.join(sorted(e['observation_id'] for e in events))+'|'+oldsha).encode()).hexdigest()
def sources(year):
    I=H/f'{year}冻结输入';meta=json.loads((H/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
    assert meta['plan_sha256']==sha(H/'冻结研究方案.md') and meta['code_sha256']==sha(H/'early_1r.py')
    assert all(sha(I/n)==v for n,v in meta['inputs'].items())
    check=json.loads((H/'组合合成时序核验.json').read_text(encoding='utf-8'))
    assert check['all_checks_pass'] and check['code_sha256']==sha(H/'early_1r.py') and check['plan_sha256']==sha(H/'冻结研究方案.md')
    a=json.loads((R48/'分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['range_code_sha256']==sha(R48/'public_range.py') and a['stream_code_sha256']==sha(RET/'public_tape_stream.py')
    return pd.read_parquet(I/'events.parquet'),pd.read_parquet(I/'paths_2r.parquet')
def task(year,fp,spec,refs,work):
    symbol,day,needs,events=spec
    prior=ROOT/'work'/f'entry1s51_{year}'/'tape'/(previous.key_for(previous.fingerprint(year),spec)+'.json')
    if not prior.is_file():return {'status':'error','error':'missing_prior_checkpoint','contract':symbol,'day':day}
    oldsha=sha(prior);dest=work/(key(fp,spec,oldsha)+'.json')
    if dest.exists():return json.loads(dest.read_text(encoding='utf-8'))
    old=json.loads(prior.read_text(encoding='utf-8'));assert old['status']=='verified'
    oldrows={r['observation_id']:r for r in old['rows']};assert set(oldrows)=={e['observation_id'] for e in events}
    archives=[a for a in old['archives'] if a['kind']=='aggTrades'];blocks={e['observation_id']:[] for e in events};found=[]
    error=''
    for attempt in range(3):
      try:
        while psutil.virtual_memory().available<500*1024**2:guard();time.sleep(3)
        guard()
        for source in archives:
            windows={e['observation_id']:(int(e['trigger_minute']),int(e['quarter_end'])+60000) for e in events}
            got,meta=public_range.fetch(symbol,source['day'],windows,guard)
            if meta['sha256']!=source['sha256'] or meta['bytes']!=source['bytes']:raise ValueError('public_archive_changed')
            found.append(meta)
            for e in events:blocks[e['observation_id']].extend(got[e['observation_id']])
        rows=[]
        for e in events:
            obs=e['observation_id'];row=oldrows[obs];assert row['status']=='qualified' and blocks[obs]
            tape=pd.concat(blocks[obs],ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort');paths={}
            for original in refs[refs.observation_id.eq(obs)].to_dict('records'):
                variant=original['variant'];priorpath=row['paths'][variant];assert priorpath['status']==original['status']=='verified'
                for k in ('entry_ts','entry_raw','entry_fill','exit_signal_ts','exit_ts','exit_raw','exit_fill','initial_stop'):
                    if k.endswith('_ts'):assert int(priorpath[k])==int(original[k])
                    else:assert np.isclose(priorpath[k],original[k],rtol=1e-11,atol=1e-12)
                assert priorpath['reason']==original['reason']
                lev=int(variant.rsplit('_',1)[1].rstrip('x'));paths[f'one_second_1r_{lev}x']=early_1r.decide(e,original,tape)
            rows.append({'observation_id':obs,'status':'qualified','paths':paths})
        out={'contract':symbol,'day':day,'needs_next':needs,'status':'verified','archives':found,
             'upstream_checkpoint_sha256':oldsha,'rows':rows};guard()
        temp=dest.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(dest)
        return out
      except Exception as exc:
        error=type(exc).__name__+':'+str(exc)[:150]
        if 'headroom' in error or 'stream_cap' in error or 'window_exceeds' in error:break
        if attempt<2:time.sleep(attempt+1)
        blocks={e['observation_id']:[] for e in events};found=[]
    return {'status':'error','error':error,'contract':symbol,'day':day}
def main(year):
    events,refs=sources(year);fp=fingerprint(year);work=ROOT/'work'/f'early1r58_{year}'/'tape';work.mkdir(parents=True,exist_ok=True)
    groups=[(s,d,bool(n),g.to_dict('records')) for (s,d,n),g in events.groupby(['contract','day','needs_next'])]
    fp51=previous.fingerprint(year);base=ROOT/'work'/f'entry1s51_{year}'/'tape'
    def size(spec):
        f=base/(previous.key_for(fp51,spec)+'.json')
        if not f.exists():return 10**12
        return sum(a.get('bytes',0) for a in json.loads(f.read_text(encoding='utf-8'))['archives'] if a['kind']=='aggTrades')
    groups.sort(key=lambda spec:(size(spec),spec[1],spec[0]));done=0;errors=[]
    print('EARLY1R58_TASKS',year,len(groups),'entries',len(events),'paths',len(refs),flush=True)
    for spec in groups:
        if shutil.disk_usage(ROOT).free<2_200_000_000:break
        z=task(year,fp,spec,refs,work)
        if z['status']!='verified':
            errors.append({'contract':z['contract'],'day':z['day'],'error':z['error']})
            if 'headroom' in z['error']:break
        done+=1
        if done%5==0:print('EARLY1R58_PROGRESS',year,done,'/',len(groups),'errors',len(errors),flush=True)
    out={'year':year,'processed_groups':done,'total_groups':len(groups),'errors':errors,'fingerprint':fp,
         'note':'Only matched prequalified 1s entries; unresolved archives remain unknown.'}
    (H/f'{year}一秒一倍逐笔进度.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EARLY1R58_STOP',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
