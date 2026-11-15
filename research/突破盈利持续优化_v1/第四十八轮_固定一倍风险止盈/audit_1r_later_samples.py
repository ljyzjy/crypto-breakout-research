"""Independently replay selected 1R public tapes in a later frozen period."""
import hashlib,json,shutil,sys,time
from pathlib import Path
import pandas as pd,psutil
import run_1r_later as runner
from audit_1r_2023_samples import independent
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as stream
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def main(year):
    I=H/f'{year}冻结输入';events=pd.read_parquet(I/'qualified_entries.parquet');refs=pd.read_parquet(I/'reference_2r_paths.parquet')
    fp=hashlib.sha256((H/'run_1r_later.py').read_bytes()+(H/'冻结研究方案.md').read_bytes()+(H/f'{year}输入冻结哈希.json').read_bytes()+
                      (H/'exit_1r.py').read_bytes()+(P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest()
    work=ROOT/'work'/f'exit1r48_{year}'/'tape';available=[]
    for (sym,day,n),g in events.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));path=work/(runner.key_for(fp,spec)+'.json')
        if not path.exists():continue
        rec=json.loads(path.read_text(encoding='utf-8'))
        for row in rec['rows']:
            if row['status']=='qualified' and any(x.get('status')=='verified' for x in row.get('paths',{}).values()):
                e=g[g.observation_id.eq(row['observation_id'])].iloc[0].to_dict();available.append((e,rec,row))
    # Sample selection covers entry origins and exit reasons; smaller verified
    # archives reduce re-download time without filtering by return or win/loss.
    available.sort(key=lambda x:(sum(int(a.get('bytes',0)) for a in x[1]['archives'] if a['kind']=='aggTrades'),x[0]['observation_id']))
    chosen=[]
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
        print('EXIT1R48_LATER_SAMPLE',year,len(results),'/',len(chosen),flush=True)
    out={'all_checks_pass':True,'year':year,'samples':results,'paths_checked':sum(x['paths_checked'] for x in results),
         'note':'Independent scalar first-touch replay; smaller source archives prioritized within entry-origin and exit-reason coverage.'}
    (H/f'{year}一倍止盈逐笔独立抽查.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_LATER_SAMPLE_PASS',year,len(results),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
