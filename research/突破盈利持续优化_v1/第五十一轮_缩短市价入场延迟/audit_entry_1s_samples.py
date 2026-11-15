"""Independently reconstruct 1-second entry and 2R exits on public tapes."""
import json,math,shutil,sys,time
from pathlib import Path
import pandas as pd,psutil
import run_entry_1s as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as stream
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def independent(e,old,want,tape):
    side=int(e['side']);pairs=list(zip(tape.transact_time.astype('int64'),tape.price.astype(float)));qend=int(e['quarter_end'])
    ref=next(((t,p) for t,p in pairs if t>=int(e['entry_exec_ts'])),None)
    assert ref and ref[0]==int(e['entry_exec_ts']) and near(ref[1],e['raw_entry_5s'])
    baseline=next(((t,p) for t,p in pairs if t>=ref[0]+5000),None)
    assert baseline and baseline[0]==int(old['entry_ts']) and near(baseline[1],old['entry_raw'])
    early=next(((t,p) for t,p in pairs if t>=ref[0]+1000),None);assert early and early[0]<qend
    raw=early[1];entry=raw*(1+side*.0005);stop=float(old['initial_stop']);dist=side*(entry-stop)
    lev=int(old['variant'].rsplit('_',1)[1].rstrip('x'));trigger=float(e['signal_close']);atr=float(e['atr'])
    bad=dist<=0 or dist>1.5*atr or side*(entry-trigger)>.25*atr or dist/entry+.003>=.5*(1/lev-.01)
    if bad:signal=early[0];reason='filled_beyond_risk_budget'
    else:
        target=entry+side*2*dist;signal=qend;reason='quarter_time';i=0
        while i<len(pairs):
            t=pairs[i][0];j=i+1
            while j<len(pairs) and pairs[j][0]==t:j+=1
            if t>=early[0] and t<=qend:
                segment=[p for _,p in pairs[i:j]]
                if any(side*(p-stop)<=0 for p in segment):signal=t;reason='stop';break
                if any(side*(p-target)>=0 for p in segment):signal=t;reason='target';break
            if t>qend:break
            i=j
    exit=next(((t,p) for t,p in pairs if t>=signal+5000),None);assert exit
    assert want['status']=='verified' and int(want['entry_ts'])==early[0] and near(want['entry_raw'],raw) and near(want['entry_fill'],entry)
    assert int(want['exit_signal_ts'])==signal and want['reason']==reason and int(want['exit_ts'])==exit[0]
    assert near(want['exit_raw'],exit[1]) and near(want['exit_fill'],exit[1]*(1-side*.0005))
def main(year):
    I=H/f'{year}冻结输入';events=pd.read_parquet(I/'qualified_entries.parquet');refs=pd.read_parquet(I/'reference_2r_paths.parquet')
    batch=H/f'{year}一秒入场分批'/'动态池逐笔信号筛查.parquet'
    snapshot=pd.read_parquet(batch);eligible=set(snapshot.loc[snapshot.replay_status.eq('qualified'),'observation_id'])
    fp=runner.fingerprint(year);work=ROOT/'work'/f'entry1s51_{year}'/'tape';available=[]
    for (sym,day,n),g in events.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));path=work/(runner.key_for(fp,spec)+'.json')
        if not path.exists():continue
        rec=json.loads(path.read_text(encoding='utf-8'))
        for row in rec['rows']:
            if row['observation_id'] in eligible and row['status']=='qualified' and any(x.get('status')=='verified' for x in row.get('paths',{}).values()):
                e=g[g.observation_id.eq(row['observation_id'])].iloc[0].to_dict();available.append((e,rec,row))
    available.sort(key=lambda x:(sum(int(a.get('bytes',0)) for a in x[1]['archives'] if a['kind']=='aggTrades'),x[0]['observation_id']));chosen=[]
    for origin in ('original','retest'):
        x=next((v for v in available if v[0]['entry_origin']==origin),None)
        if x and x not in chosen:chosen.append(x)
    for reason in ('target','stop','quarter_time','filled_beyond_risk_budget'):
        x=next((v for v in available if any(p.get('status')=='verified' and p.get('reason')==reason for p in v[2].get('paths',{}).values()) and v not in chosen),None)
        if x and len(chosen)<4:chosen.append(x)
    assert len(chosen)>=2 and {x[0]['entry_origin'] for x in chosen}=={'original','retest'};results=[]
    for e,rec,row in chosen:
        while psutil.virtual_memory().available<500*1024**2:guard();time.sleep(3)
        obs=e['observation_id'];blocks=[];archives=[]
        for a in (x for x in rec['archives'] if x['kind']=='aggTrades'):
            got,meta=stream.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60_000)},guard)
            assert meta['sha256']==a['sha256'];blocks.extend(got[obs]);archives.append(meta)
        tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort');n=0
        for name,path in row['paths'].items():
            if path['status']!='verified':continue
            variant=name.replace('one_second_2r_','normal_2r_');old=refs[(refs.observation_id==obs)&(refs.variant==variant)]
            assert len(old)==1;independent(e,old.iloc[0].to_dict(),path,tape);n+=1
        results.append({'observation_id':obs,'origin':e['entry_origin'],'paths_checked':n,'archives':archives})
        print('ENTRY51_SAMPLE',year,len(results),'/',len(chosen),flush=True)
    out={'all_checks_pass':True,'year':year,'samples':results,'paths_checked':sum(x['paths_checked'] for x in results),
         'note':'Independent grouped-timestamp scalar replay of 1-second entry and 2R exit; source size prioritized within audit coverage.'}
    (H/f'{year}一秒入场逐笔独立抽查.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENTRY51_SAMPLE_PASS',year,len(results),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
