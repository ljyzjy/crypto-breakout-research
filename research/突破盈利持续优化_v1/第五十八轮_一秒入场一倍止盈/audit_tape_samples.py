"""Independently replay selected 1s/1R paths on complete public tapes."""
import json,math,shutil,sys,time
from pathlib import Path
import pandas as pd,psutil
import run_early_1r as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;FAST=P/'第五十一轮_缩短市价入场延迟'
sys.path.insert(0,str(FAST));import run_entry_1s as previous
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as stream
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def replay(e,old,want,tape):
    side=int(e['side']);qend=int(e['quarter_end']);seq=list(zip(tape.transact_time.astype('int64'),tape.price.astype(float)))
    ref=next((x for x in seq if x[0]>=int(e['entry_exec_ts'])),None);assert ref and ref[0]==int(e['entry_exec_ts']) and near(ref[1],e['raw_entry_5s'])
    entry=next((x for x in seq if x[0]>=ref[0]+1000),None);assert entry and entry[0]==int(old['entry_ts']) and near(entry[1],old['entry_raw'])
    fill=entry[1]*(1+side*.0005);stop=float(old['initial_stop']);distance=side*(fill-stop);assert near(fill,old['entry_fill'])
    if old['reason']=='filled_beyond_risk_budget':signal=entry[0];reason='filled_beyond_risk_budget'
    else:
        assert distance>0;target=fill+side*distance;signal=qend;reason='quarter_time';i=0
        while i<len(seq):
            t=seq[i][0];j=i+1
            while j<len(seq) and seq[j][0]==t:j+=1
            if entry[0]<=t<=qend:
                prices=[v for _,v in seq[i:j]]
                if any(side*(v-stop)<=0 for v in prices):signal=t;reason='stop';break
                if any(side*(v-target)>=0 for v in prices):signal=t;reason='target';break
            if t>qend:break
            i=j
    exit=next((x for x in seq if x[0]>=signal+5000),None);assert exit
    assert want['status']=='verified' and int(want['entry_ts'])==entry[0] and near(want['entry_raw'],entry[1]) and near(want['entry_fill'],fill)
    assert int(want['exit_signal_ts'])==signal and int(want['exit_ts'])==exit[0] and want['reason']==reason
    assert near(want['exit_raw'],exit[1]) and near(want['exit_fill'],exit[1]*(1-side*.0005)) and exit[0]<=int(old['exit_ts'])
def main(year):
    events,refs=runner.sources(year);fp=runner.fingerprint(year);fp51=previous.fingerprint(year)
    olddir=ROOT/'work'/f'entry1s51_{year}'/'tape';newdir=ROOT/'work'/f'early1r58_{year}'/'tape';available=[]
    for (sym,day,n),g in events.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));prior=olddir/(previous.key_for(fp51,spec)+'.json')
        if not prior.exists():continue
        f=newdir/(runner.key(fp,spec,runner.sha(prior))+'.json')
        if not f.exists():continue
        z=json.loads(f.read_text(encoding='utf-8'))
        for row in z['rows']:
            if row['status']!='qualified' or not any(p.get('status')=='verified' for p in row.get('paths',{}).values()):continue
            e=g[g.observation_id.eq(row['observation_id'])].iloc[0].to_dict();available.append((e,z,row))
    available.sort(key=lambda x:(sum(int(a.get('bytes',0)) for a in x[1]['archives']),x[0]['observation_id']));chosen=[]
    for origin in ('original','retest'):
        x=next((v for v in available if v[0]['entry_origin']==origin),None)
        if x and x not in chosen:chosen.append(x)
    for reason in ('target','stop','quarter_time','filled_beyond_risk_budget'):
        x=next((v for v in available if any(p.get('status')=='verified' and p.get('reason')==reason for p in v[2]['paths'].values()) and v not in chosen),None)
        if x and len(chosen)<4:chosen.append(x)
    assert len(chosen)>=2 and {x[0]['entry_origin'] for x in chosen}=={'original','retest'}
    results=[]
    for e,cp,row in chosen:
        while psutil.virtual_memory().available<500*1024**2:guard();time.sleep(3)
        obs=e['observation_id'];blocks=[];archives=[]
        for a in cp['archives']:
            got,meta=stream.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60000)},guard)
            assert meta['sha256']==a['sha256'];blocks.extend(got[obs]);archives.append(meta)
        tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort');n=0
        for variant,want in row['paths'].items():
            if want['status']!='verified':continue
            prior=refs[(refs.observation_id==obs)&(refs.variant==variant.replace('one_second_1r_','one_second_2r_'))]
            assert len(prior)==1;replay(e,prior.iloc[0].to_dict(),want,tape);n+=1
        results.append({'observation_id':obs,'entry_origin':e['entry_origin'],'paths_checked':n,'archives':archives})
        print('EARLY1R58_SAMPLE',year,len(results),'/',len(chosen),flush=True)
    out={'all_checks_pass':True,'year':year,'samples':results,'paths_checked':sum(x['paths_checked'] for x in results),
         'note':'Independent grouped-timestamp 1R replay, public prints only.'}
    (H/f'{year}一秒一倍逐笔独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EARLY1R58_SAMPLE_PASS',year,len(results),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
