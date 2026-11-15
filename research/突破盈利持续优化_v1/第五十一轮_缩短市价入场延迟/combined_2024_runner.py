"""Share verified tape reads across two separately frozen 2024 comparisons."""
import hashlib,json,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;R48=P/'第四十八轮_固定一倍风险止盈'
sys.path.insert(0,str(R48));import public_range,run_1r_later as one_r,exit_1r
sys.path.insert(0,str(H));import run_entry_1s as early
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fingerprint_1r():
    y='2024';pub=P/'第四十七轮_一次重新突破确认'
    return hashlib.sha256((R48/'run_1r_later.py').read_bytes()+(R48/'冻结研究方案.md').read_bytes()+(R48/f'{y}输入冻结哈希.json').read_bytes()+
                          (R48/'exit_1r.py').read_bytes()+(pub/'public_tape_stream.py').read_bytes()).hexdigest()
def write_checkpoint(spec,record,captured,fp,work,codehash):
    if record['status']!='verified' or not captured:return False
    rows=[]
    for old in record['rows']:
        obs=old['observation_id']
        if old['status']!='qualified':rows.append({'observation_id':obs,'status':old['status']});continue
        assert obs in captured and captured[obs],('missing_dual_path',obs)
        rows.append({'observation_id':obs,'status':'qualified','paths':captured[obs]})
    out={'contract':record['contract'],'day':record['day'],'needs_next':record['needs_next'],'status':'verified',
         'archives':record['archives'],'rows':rows,'paired_reader_sha256':codehash}
    work.mkdir(parents=True,exist_ok=True);file=work/(one_r.key_for(fp,spec)+'.json')
    if file.exists():return False
    temp=file.with_suffix('.partial');temp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(file)
    return True
def main():
    audit=json.loads((R48/'分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['range_code_sha256']==sha(R48/'public_range.py')
    assert audit['stream_code_sha256']==sha(P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py')
    test=json.loads((H/'共同读取合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['runner_sha256']==sha(Path(__file__))
    assert test['one_r_sha256']==sha(R48/'exit_1r.py') and test['one_second_sha256']==sha(H/'entry_1s.py')
    real=json.loads((H/'共同读取真实逐笔核验.json').read_text(encoding='utf-8'))
    assert real['all_checks_pass'] and real['runner_sha256']==sha(Path(__file__))
    frozen=json.loads((R48/'2024输入冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(R48/'冻结研究方案.md')==frozen['plan_sha256']
    for n,v in frozen['inputs'].items():assert sha(R48/'2024冻结输入'/n)==v
    a=json.loads((H/'2024输入冻结哈希.json').read_text(encoding='utf-8'))
    assert a['inputs']['reference_2r_paths.parquet']==frozen['inputs']['reference_2r_paths.parquet']
    left=pd.read_parquet(H/'2024冻结输入'/'qualified_entries.parquet').sort_values('observation_id').reset_index(drop=True)
    right=pd.read_parquet(R48/'2024冻结输入'/'qualified_entries.parquet').sort_values('observation_id').reset_index(drop=True)
    pd.testing.assert_frame_equal(left[right.columns],right,check_dtype=False,check_exact=True)
    fp=fingerprint_1r();work=ROOT/'work'/'exit1r48_2024'/'tape';original_task=early.task;original_decide=early.entry_1s.decide
    def dual_task(year,fp51,spec,index,refs,work51):
        captured={}
        def dual_decide(e,old,tape):
            fast=original_decide(e,old,tape);lev=int(old['variant'].rsplit('_',1)[1].rstrip('x'))
            captured.setdefault(e['observation_id'],{})[f'normal_1r_{lev}x']=exit_1r.decide(e,old,tape)
            return fast
        early.entry_1s.decide=dual_decide
        try:result=original_task(year,fp51,spec,index,refs,work51)
        finally:early.entry_1s.decide=original_decide
        if write_checkpoint(spec,result,captured,fp,work,sha(Path(__file__))):
            print('DUAL_2024_ONE_R_CHECKPOINT',spec[0],spec[1],flush=True)
        return result
    early.direct.fetch=public_range.fetch;early.task=dual_task;early.main('2024')
if __name__=='__main__':main()
