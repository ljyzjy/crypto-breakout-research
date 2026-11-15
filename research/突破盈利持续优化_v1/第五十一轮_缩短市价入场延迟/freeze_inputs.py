"""Freeze identical qualified entries and audited 2R paths by historical period."""
import hashlib,json,shutil,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent/'第四十八轮_固定一倍风险止盈'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(year):
    I=H/f'{year}冻结输入';I.mkdir(exist_ok=True);out=H/f'{year}输入冻结哈希.json'
    if out.exists():
        z=json.loads(out.read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==z['plan_sha256']
        for n,v in z['inputs'].items():assert sha(I/n)==v
        return
    test=json.loads((H/'一秒入场合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==sha(H/'entry_1s.py')
    old=json.loads((P/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'));source=P/f'{year}冻结输入'
    names=['baseline_signal.parquet','baseline_paths.parquet','baseline_ledger.parquet',
           'retry_signal.parquet','retry_paths.parquet','retry_ledger.parquet','reference_2r_paths.parquet']
    if year!='2023':names.append('provenance.json')
    for n in names:
        src=source/n;assert sha(src)==old['inputs'][n];dst=I/n
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    base=pd.read_parquet(I/'baseline_signal.parquet');retry=pd.read_parquet(I/'retry_signal.parquet')
    a=base[base.status.eq('qualified')].copy();a['entry_origin']='original'
    b=retry[retry.status.eq('qualified')].copy();b['entry_origin']='retest'
    cols=['observation_id','contract','day','needs_next','source_year','quarter_start','quarter_end','trigger_minute',
          'side','decision_ts','entry_exec_ts','raw_entry_5s','entry_origin','signal_close','atr','stop_price','level','upper','lower']
    events=pd.concat([a[cols],b[cols]],ignore_index=True);assert events.observation_id.is_unique
    prior=pd.read_parquet(source/'qualified_entries.parquet');assert set(events.observation_id)==set(prior.observation_id)
    events.to_parquet(I/'qualified_entries.parquet',index=False);names.append('qualified_entries.parquet')
    z={'year':year,'plan_sha256':sha(H/'冻结研究方案.md'),'code_sha256':sha(H/'entry_1s.py'),
       'inputs':{n:sha(I/n) for n in names},'events':len(events),
       'note':'Original prechecks, entry decisions and candidates are fixed before one-second replay.'}
    out.write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENTRY51_INPUTS_FROZEN',year,len(events),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
