"""Compare diskless ZIP parsing and full tape decisions against two saved replays."""
import hashlib,json,math,sys
from pathlib import Path
import pandas as pd
import public_tape_stream as direct
H=Path(__file__).resolve().parent;D=H.parent/'第四十六轮_固定十一加密币跨时段';sys.path.insert(0,str(D))
import stream_fixed11_tapes as disk
I=D/'逐笔冻结输入'
def equal(a,b,path='root'):
    if isinstance(a,dict):
        assert isinstance(b,dict) and set(a)==set(b),path
        for k in a:equal(a[k],b[k],path+'.'+str(k))
    elif isinstance(a,list):
        assert isinstance(b,list) and len(a)==len(b),path
        for i,(x,y) in enumerate(zip(a,b)):equal(x,y,path+f'[{i}]')
    elif isinstance(a,float):assert isinstance(b,(int,float)) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12),(path,a,b)
    else:assert a==b,(path,a,b)
def main():
    synthetic=json.loads((H/'无落盘逐笔读取合成核验.json').read_text(encoding='utf-8'))
    assert synthetic['all_checks_pass'] and synthetic['stream_code_sha256']==hashlib.sha256((H/'public_tape_stream.py').read_bytes()).hexdigest()
    previous=json.loads((D/'新逐笔读取一致性核验.json').read_text(encoding='utf-8'));assert previous['all_checks_pass']
    candidates=pd.concat([pd.read_parquet(I/'2024_candidates.parquet'),pd.read_parquet(I/'2026_candidates.parquet')],ignore_index=True).set_index('observation_id')
    samples=[]
    for sample in previous['samples']:
        obs=sample['observation_id'];e=candidates.loc[obs].to_dict();e['observation_id']=obs
        spec=(e['contract'],e['day'],bool(e['needs_next']),[e]);file=disk.WORK/(disk.key_for(spec)+'.json')
        old=json.loads(file.read_text(encoding='utf-8'));assert old['status']=='verified'
        body,meta=disk.engine.archive('klines',e['contract'],e['day']);bars=disk.engine.minute_bars(body,e['day']);del body
        blocks=[];archives=[]
        for a in (z for z in old['archives'] if z['kind']=='aggTrades'):
            result,archive=direct.fetch(e['contract'],a['day'],{obs:(int(e['trigger_minute']),int(e['quarter_end'])+60_000)})
            assert archive['sha256']==a['sha256'];blocks.extend(result[obs]);archives.append(archive)
        tape=pd.concat(blocks,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        row={'observation_id':obs,**disk.engine.decide(e,tape,bars)}
        equal(old['rows'][0],row)
        samples.append({'observation_id':obs,'paths_checked':len(row.get('paths',{})),'archives':archives})
        print('PUBLIC_TAPE_STREAM_REAL_SAMPLE',len(samples),'/2',flush=True)
    assert len(samples)==2
    out={'all_checks_pass':True,'samples':samples,'paths_checked':sum(x['paths_checked'] for x in samples),
         'stream_code_sha256':hashlib.sha256((H/'public_tape_stream.py').read_bytes()).hexdigest(),
         'note':'Checks public aggregated trades only; no actual market order fills reconstructed.'}
    (H/'无落盘逐笔读取真实样本核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PUBLIC_TAPE_STREAM_REAL_PASS',len(samples),flush=True)
if __name__=='__main__':main()
