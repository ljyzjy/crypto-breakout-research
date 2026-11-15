"""Independently re-fetch and replay selected 2023 one-R trade tapes."""
import json,math,shutil,sys,time
from pathlib import Path
import pandas as pd,psutil
import run_1r_2023 as runner
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as stream
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def independent(e,old,expected,tape):
    side=int(e['side']);qend=int(e['quarter_end']);pairs=list(zip(tape.transact_time.astype('int64'),tape.price.astype(float)))
    reference=next(((t,p) for t,p in pairs if t>=int(e['entry_exec_ts'])),None)
    assert reference and reference[0]==int(e['entry_exec_ts']) and near(reference[1],e['raw_entry_5s'])
    entry=next(((t,p) for t,p in pairs if t>=int(e['entry_exec_ts'])+5000),None);assert entry
    fill=entry[1]*(1+side*.0005);stop=float(old['initial_stop']);risk=side*(fill-stop)
    assert entry[0]==int(old['entry_ts']) and near(entry[1],old['entry_raw']) and near(fill,old['entry_fill'])
    if old['reason']=='filled_beyond_risk_budget': signal=entry[0];reason='filled_beyond_risk_budget'
    else:
        assert risk>0;target=fill+side*risk;signal=qend;reason='quarter_time'
        for t,p in pairs:
            if t<entry[0]:continue
            if t>qend:break
            if side*(p-stop)<=0:signal=t;reason='stop';break
            if side*(p-target)>=0:signal=t;reason='target';break
    exit=next(((t,p) for t,p in pairs if t>=signal+5000),None);assert exit
    assert expected['status']=='verified' and int(expected['entry_ts'])==entry[0] and near(expected['entry_raw'],entry[1])
    assert near(expected['entry_fill'],fill) and int(expected['exit_signal_ts'])==signal and expected['reason']==reason
    assert int(expected['exit_ts'])==exit[0] and near(expected['exit_raw'],exit[1]) and near(expected['exit_fill'],exit[1]*(1-side*.0005))
def main():
    events=pd.read_parquet(H/'2023冻结输入'/'qualified_entries.parquet');refs=pd.read_parquet(H/'2023冻结输入'/'reference_2r_paths.parquet')
    available=[]
    for (sym,day,n),g in events.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));path=runner.WORK/(runner.key_for(spec)+'.json')
        if not path.exists():continue
        rec=json.loads(path.read_text(encoding='utf-8'))
        for row in rec['rows']:
            if row['status']=='qualified' and any(x.get('status')=='verified' for x in row.get('paths',{}).values()):
                e=g[g.observation_id.eq(row['observation_id'])].iloc[0].to_dict();available.append((e,rec,row))
    # Smaller full-SHA archives are re-read first while covering both entry
    # origins and available exit reasons; selection does not use profit.
    available.sort(key=lambda x:(sum(int(a.get('bytes',0)) for a in x[1]['archives'] if a['kind']=='aggTrades'),x[0]['observation_id']))
    chosen=[]
    # Audit original and retry entries, then distinct exit reasons when available.
    for origin in ('original','retest'):
        x=next((v for v in available if v[0]['entry_origin']==origin),None)
        if x and x not in chosen:chosen.append(x)
    for reason in ('target','stop','quarter_time','filled_beyond_risk_budget'):
        x=next((v for v in available if any(p.get('status')=='verified' and p.get('reason')==reason for p in v[2].get('paths',{}).values()) and v not in chosen),None)
        if x and len(chosen)<4:chosen.append(x)
    assert len(chosen)>=2 and {x[0]['entry_origin'] for x in chosen}=={'original','retest'}
    results=[]
    for e,rec,row in chosen:
        while psutil.virtual_memory().available<500*1024**2:guard();time.sleep(3)
        obs=e['observation_id'];blocks=[];archives=[]
        for a in (x for x in rec['archives'] if x['kind']=='aggTrades'):
            got,meta=stream.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60_000)},guard)
            assert meta['sha256']==a['sha256'];blocks.extend(got[obs]);archives.append(meta)
        tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort');n=0
        for name,path in row['paths'].items():
            if path['status']!='verified':continue
            old=refs[(refs.observation_id==obs)&(refs.variant==name.replace('_1r_','_2r_'))]
            assert len(old)==1;independent(e,old.iloc[0].to_dict(),path,tape);n+=1
        results.append({'observation_id':obs,'origin':e['entry_origin'],'paths_checked':n,'archives':archives})
        print('EXIT1R48_INDEPENDENT_SAMPLE',len(results),'/',len(chosen),flush=True)
    out={'all_checks_pass':True,'samples':results,'paths_checked':sum(x['paths_checked'] for x in results),
         'note':'Independent scalar first-touch replay; smaller SHA-verified source archives prioritized within entry-origin and exit-reason coverage.'}
    (H/'2023一倍止盈逐笔独立抽查.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_SAMPLE_AUDIT_PASS',len(results),flush=True)
if __name__=='__main__':main()
