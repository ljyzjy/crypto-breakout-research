"""Check independent paired outputs and atomic dual checkpoint keys."""
import hashlib,json
from pathlib import Path
import pandas as pd
import combined_2024_runner as dual
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    e={'observation_id':'synthetic|TESTUSDT|0','side':1,'quarter_end':30000,'entry_exec_ts':5000,'raw_entry_5s':100.,'signal_close':100.,'atr':4.}
    old={'status':'verified','variant':'normal_2r_20x','entry_ts':10000,'entry_raw':100.1,'entry_fill':100.1*1.0005,
         'exit_signal_ts':30000,'exit_ts':35000,'exit_raw':100.,'initial_stop':99.,'reason':'quarter_time'}
    tape=pd.DataFrame({'transact_time':[0,5000,6000,10000,12000,17000,30000,35000],
                       'price':[100.,100.,100.,100.1,102.2,102.3,100.,100.]})
    fast=dual.early.entry_1s.decide(e,old,tape);one=dual.exit_1r.decide(e,old,tape)
    assert fast['status']=='verified' and fast['entry_ts']==6000 and fast['target_r']==2.
    assert one['status']=='verified' and one['entry_ts']==10000 and one['target_r']==1.
    spec=('TESTUSDT','2024-01-01',False,[e]);rec={'contract':'TESTUSDT','day':'2024-01-01','needs_next':False,
        'status':'verified','archives':[],'rows':[{'observation_id':e['observation_id'],'status':'qualified'}]}
    captured={e['observation_id']:{'normal_1r_20x':one}};fp='synthetic_fingerprint';work=ROOT/'work'/'dual_reader_synthetic'
    file=work/(dual.one_r.key_for(fp,spec)+'.json')
    if not file.exists():assert dual.write_checkpoint(spec,rec,captured,fp,work,sha(H/'combined_2024_runner.py'))
    saved=json.loads(file.read_text(encoding='utf-8'));assert saved['rows'][0]['paths']['normal_1r_20x']==one
    assert not dual.write_checkpoint(spec,rec,captured,fp,work,sha(H/'combined_2024_runner.py'))
    assert not dual.write_checkpoint(spec,rec,{},fp,work,sha(H/'combined_2024_runner.py'))
    z={'all_checks_pass':True,'runner_sha256':sha(H/'combined_2024_runner.py'),'one_r_sha256':sha(dual.R48/'exit_1r.py'),
       'one_second_sha256':sha(H/'entry_1s.py'),'checks':['independent_entry_rules','matching_one_r_checkpoint_key','atomic_idempotent_write','missing_path_not_written']}
    (H/'共同读取合成核验.json').write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL_2024_SYNTHETIC_PASS',flush=True)
if __name__=='__main__':main()
