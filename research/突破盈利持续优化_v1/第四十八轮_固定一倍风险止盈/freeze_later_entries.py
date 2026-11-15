"""Freeze each completed later period's causal entries before 1R replay."""
import hashlib,json,shutil,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent/'第四十七轮_一次重新突破确认'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze(year):
    I=H/f'{year}冻结输入';I.mkdir(exist_ok=True);out=H/f'{year}输入冻结哈希.json'
    if out.exists():
        z=json.loads(out.read_text(encoding='utf-8'));assert z['plan_sha256']==sha(H/'冻结研究方案.md')
        for n,v in z['inputs'].items():assert sha(I/n)==v
        return
    L=P/'跨期冻结输入';R=P/f'{year}重试分批'
    files={'baseline_signal.parquet':L/f'{year}_signal.parquet','baseline_paths.parquet':L/f'{year}_paths.parquet',
           'baseline_ledger.parquet':L/f'{year}_ledger.parquet','provenance.json':L/'provenance.json',
           'retry_signal.parquet':R/'动态池逐笔信号筛查.parquet','retry_paths.parquet':R/'动态池延迟市价路径.parquet',
           'retry_ledger.parquet':R/'动态池单位收益与风险.parquet','retry_quality.json':R/'动态池单位筛查完整性.json',
           'retry_audit.json':P/'单次重试净账本独立核验.json','retry_plan.md':P/'冻结研究方案.md'}
    assert json.loads(files['retry_quality.json'].read_text(encoding='utf-8'))['complete']
    audit=json.loads(files['retry_audit.json'].read_text(encoding='utf-8'));assert audit['all_checks_pass']
    for lev in (10,20):assert any(str(x['year'])==year and x['strategy']=='single_retest' and x['leverage']==lev for x in audit['groups'])
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
    z={'year':year,'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{n:sha(I/n) for n in names},'events':len(events),'reference_paths':len(paths),
       'note':'Entry qualification is causal; previous outcome files are used to verify paired entries and compare exits, not to select events.'}
    out.write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_INPUTS_FROZEN',year,len(events),'paths',len(paths),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');freeze(sys.argv[1])
