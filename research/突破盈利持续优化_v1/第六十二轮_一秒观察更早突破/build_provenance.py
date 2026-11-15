"""Trace every known first-breakout candidate to its original public SHA."""
import hashlib,json,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;R43=P/'第四十三轮_旧十一币2023年复核'
sys.path.insert(0,str(R43));import extract_old11_tapes as source,stream_tapes_2023 as stream,stream_tapes_2023_tight as tight
KNOWN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def archives_for(z):
    day=z['day'];daily=[a for a in z['archives'] if a['kind']=='klines' and a['day']==day];assert len(daily)==1
    aggs={a['day']:{'sha256':a['sha256'],'bytes':a['bytes']} for a in z['archives'] if a['kind']=='aggTrades'};assert aggs
    return {'daily_sha256':daily[0]['sha256'],'agg_archives':aggs}
def source_2023(wanted):
    found={}
    for module in (source,stream,tight):
        for p in sorted(module.WORK.glob('*.json')):
            z=json.loads(p.read_text(encoding='utf-8'))
            if z.get('status')!='verified':continue
            key=module.FP+'|'+z['contract']+'|'+z['day']+'|'+str(z['needs_next'])+'|'+'|'.join(sorted(x['observation_id'] for x in z['rows']))
            assert p.stem==hashlib.sha256(key.encode()).hexdigest()
            for row in z['rows']:
                obs=row['observation_id']
                if obs not in wanted:continue
                assert row['status']==wanted[obs]
                rec={'source':'2023_verified_checkpoint','checkpoint':str(p),'checkpoint_sha256':sha(p),**archives_for(z)}
                if obs in found:
                    assert found[obs]['daily_sha256']==rec['daily_sha256'] and found[obs]['agg_archives']==rec['agg_archives']
                else:found[obs]=rec
    return found
def source_later(wanted,path):
    trace={x['observation_id']:x for x in json.loads(path.read_text(encoding='utf-8'))};found={}
    for obs,status in wanted.items():
        x=trace.get(obs)
        if not x or x['source'] not in ('reused_tape','new_tape'):continue
        if x['source']=='reused_tape':
            file=Path(x['old_checkpoint']);z=json.loads(file.read_text(encoding='utf-8'));assert z['status']=='verified'
            assert any(r['observation_id']==obs for r in z['rows']);rec={'source':x['source'],'checkpoint':str(file),'checkpoint_sha256':sha(file),**archives_for(z)}
            assert rec['daily_sha256']==x['daily_sha256']
        else:
            bars=[a for a in x['archives'] if a['kind']=='klines'];aggs=[a for a in x['archives'] if a['kind']=='aggTrades']
            assert len(bars)==1 and aggs
            rec={'source':x['source'],'daily_sha256':bars[0]['sha256'],'agg_archives':{a['day']:{'sha256':a['sha256'],'bytes':a['bytes']} for a in aggs}}
        found[obs]=rec
    return found
def main():
    for year in ('2023','2024','2026'):
        I=H/f'{year}冻结输入';f=json.loads((H/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
        assert f['plan_sha256']==sha(H/'冻结研究方案.md') and f['decision_code_sha256']==sha(H/'one_second_observation.py')
        assert all(sha(I/n)==v for n,v in f['input_sha256'].items())
        signal=pd.read_parquet(I/'baseline_signal.parquet');wanted={r.observation_id:r.status for r in signal.itertuples(index=False) if r.status in KNOWN}
        found=source_2023(wanted) if year=='2023' else source_later(wanted,I/'provenance.json')
        missing=sorted(set(wanted)-set(found));assert not missing,(year,missing)
        z={'year':year,'known_candidates':len(wanted),'baseline_unknown_candidates':len(signal)-len(wanted),
           'input_manifest_sha256':sha(H/f'{year}输入冻结哈希.json'),'code_sha256':sha(Path(__file__)),'events':found,
           'note':'Known source status only; archive SHA must match again before replay.'}
        output=H/f'{year}已知候选逐笔来源.json';assert not output.exists();output.write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
        print('OBS62_PROVENANCE',year,len(found),'unknown',len(signal)-len(wanted),flush=True)
if __name__=='__main__':main()
