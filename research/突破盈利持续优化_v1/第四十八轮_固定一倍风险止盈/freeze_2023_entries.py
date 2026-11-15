"""Freeze causal original/retry entries before computing the 1R alternative."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent/'第四十七轮_一次重新突破确认';I=H/'2023冻结输入';I.mkdir(exist_ok=True)
files={'baseline_signal.parquet':P/'2023冻结输入'/'baseline_signal.parquet',
       'baseline_paths.parquet':P/'2023冻结输入'/'baseline_paths.parquet',
       'baseline_ledger.parquet':P/'2023冻结输入'/'baseline_ledger.parquet',
       'retry_signal.parquet':P/'2023重试分批'/'动态池逐笔信号筛查.parquet',
       'retry_paths.parquet':P/'2023重试分批'/'动态池延迟市价路径.parquet',
       'retry_ledger.parquet':P/'2023重试分批'/'动态池单位收益与风险.parquet',
       'retry_audit.json':P/'2023单次重试对照独立核验.json',
       'retry_plan.md':P/'冻结研究方案.md','minute_sources.json':P/'2023冻结输入'/'minute_sources.json'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    target=H/'2023输入冻结哈希.json'
    if target.exists():
        x=json.loads(target.read_text(encoding='utf-8'));assert x['plan_sha256']==sha(H/'冻结研究方案.md')
        for n,v in x['inputs'].items():assert sha(I/n)==v
        return
    assert json.loads(files['retry_audit.json'].read_text(encoding='utf-8'))['all_checks_pass']
    test=json.loads((H/'一倍止盈合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==sha(H/'exit_1r.py')
    for name,src in files.items():
        dst=I/name
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    base=pd.read_parquet(I/'baseline_signal.parquet');retry=pd.read_parquet(I/'retry_signal.parquet')
    assert base.observation_id.is_unique and retry.observation_id.is_unique
    original=base[base.status.eq('qualified')].copy();original['entry_origin']='original'
    again=retry[retry.status.eq('qualified')].copy();again['entry_origin']='retest'
    cols=['observation_id','contract','day','needs_next','source_year','quarter_start','quarter_end','trigger_minute',
          'side','decision_ts','entry_exec_ts','raw_entry_5s','entry_origin']
    events=pd.concat([original[cols],again[cols]],ignore_index=True);assert events.observation_id.is_unique
    paths=pd.concat([pd.read_parquet(I/'baseline_paths.parquet'),pd.read_parquet(I/'retry_paths.parquet')],ignore_index=True)
    paths=paths[paths.variant.isin(['normal_2r_10x','normal_2r_20x'])&paths.observation_id.isin(events.observation_id)]
    assert not paths.duplicated(['observation_id','variant']).any()
    events.to_parquet(I/'qualified_entries.parquet',index=False);paths.to_parquet(I/'reference_2r_paths.parquet',index=False)
    names=[*files,'qualified_entries.parquet','reference_2r_paths.parquet']
    x={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{n:sha(I/n) for n in names},'events':len(events),'reference_paths':len(paths),
       'note':'Entry qualification is causal; source/path outcomes are used only for paired validation, not to choose entries.'}
    target.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_2023_INPUTS_FROZEN',len(events),'paths',len(paths),flush=True)
if __name__=='__main__':main()
