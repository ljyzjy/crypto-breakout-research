"""Independently verify both frozen rules on one identical public tape."""
import json,shutil,sys,time
from pathlib import Path
import pandas as pd,psutil
import combined_2024_runner as dual
import audit_entry_1s_samples as audit_fast
sys.path.insert(0,str(dual.R48));from audit_1r_2023_samples import independent as audit_one_r
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent
def guard():
    if shutil.disk_usage(ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available<250*1024**2:raise RuntimeError('memory_headroom')
def main():
    I=H/'2024冻结输入';d=pd.read_parquet(I/'qualified_entries.parquet');refs=pd.read_parquet(I/'reference_2r_paths.parquet')
    fp=dual.early.fingerprint('2024');work=ROOT/'work'/'entry1s51_2024'/'tape';options=[]
    for (sym,day,n),g in d.groupby(['contract','day','needs_next']):
        spec=(sym,day,bool(n),g.to_dict('records'));path=work/(dual.early.key_for(fp,spec)+'.json')
        if not path.exists():continue
        rec=json.loads(path.read_text(encoding='utf-8'))
        for row in rec['rows']:
            if row['status']=='qualified' and any(x.get('status')=='verified' for x in row.get('paths',{}).values()):
                e=g[g.observation_id.eq(row['observation_id'])].iloc[0].to_dict()
                size=sum(int(x.get('bytes',0)) for x in rec['archives'] if x['kind']=='aggTrades');options.append((size,e,rec,row))
    assert options;_,e,rec,row=min(options,key=lambda x:(x[0],x[1]['observation_id']));obs=e['observation_id'];blocks=[];archives=[]
    while psutil.virtual_memory().available<500*1024**2:guard();time.sleep(3)
    for a in (x for x in rec['archives'] if x['kind']=='aggTrades'):
        data,meta=dual.public_range.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60_000)},guard)
        assert meta['sha256']==a['sha256'];blocks.extend(data[obs]);archives.append(meta)
    tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort');checked=0
    for variant,path in row['paths'].items():
        if path['status']!='verified':continue
        original=variant.replace('one_second_2r_','normal_2r_');found=refs[(refs.observation_id==obs)&(refs.variant==original)]
        assert len(found)==1;old=found.iloc[0].to_dict();audit_fast.independent(e,old,path,tape)
        one=dual.exit_1r.decide(e,old,tape);assert one['status']=='verified';audit_one_r(e,old,one,tape);checked+=1
    assert checked>0
    z={'all_checks_pass':True,'observation_id':obs,'paths_checked':checked,'archives':archives,
       'runner_sha256':dual.sha(H/'combined_2024_runner.py'),
       'note':'Same verified public tape; one-second entry and 1R exit independently reconstructed by scalar audit code.'}
    (H/'共同读取真实逐笔核验.json').write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL_2024_REAL_PASS',obs,checked,flush=True)
if __name__=='__main__':main()
