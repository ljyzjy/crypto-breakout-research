"""Freeze 2024/2026 fixed-pool baseline and causal retry eligibility."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent/'第四十六轮_固定十一加密币跨时段';I=H/'跨期冻结输入';I.mkdir(exist_ok=True)
sources={'provenance.json':P/'逐笔来源追踪.json','baseline_audit.json':P/'固定十一币净账本独立核验.json',
         'minute_sources.json':P/'小块来源冻结哈希.json','tape_audit.json':P/'逐笔复用独立核验.json'}
for year in (2024,2026):
    folder=P/str(year)/'逐笔分批'
    for name,source in [('signal','动态池逐笔信号筛查.parquet'),('paths','动态池延迟市价路径.parquet'),
                        ('ledger','动态池单位收益与风险.parquet'),('quality','动态池单位筛查完整性.json')]:
        sources[f'{year}_{name}'+('.json' if name=='quality' else '.parquet')]=folder/source
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=H/'跨期输入冻结哈希.json'
    if out.exists():
        f=json.loads(out.read_text(encoding='utf-8'));assert f['plan_sha256']==sha(H/'冻结研究方案.md')
        for n,v in f['inputs'].items():assert sha(I/n)==v
        return
    assert json.loads(sources['baseline_audit.json'].read_text(encoding='utf-8'))['all_checks_pass']
    assert json.loads(sources['tape_audit.json'].read_text(encoding='utf-8'))['all_checks_pass']
    for name,src in sources.items():
        dest=I/name
        if dest.exists():assert sha(dest)==sha(src)
        else:shutil.copy2(src,dest)
        assert sha(dest)==sha(src)
    counts={}
    for year in (2024,2026):
        signal=pd.read_parquet(I/f'{year}_signal.parquet')
        selected=signal[signal.status.eq('flow_filter_not_met')&(signal.side*(signal.raw_entry_5s-signal.level)<=0)].copy()
        assert signal.observation_id.is_unique and selected.observation_id.is_unique
        name=f'{year}_retry_candidates.parquet';selected.to_parquet(I/name,index=False)
        counts[str(year)]={'candidates':len(selected),'groups':len(selected[['contract','day','needs_next']].drop_duplicates())}
    names=[*sources,*[f'{y}_retry_candidates.parquet' for y in (2024,2026)]]
    f={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{n:sha(I/n) for n in names},'counts':counts,
       'note':'Selection uses only original no-order status and five-second reference; historical periods were previously studied.'}
    out.write_text(json.dumps(f,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_LATER_INPUTS_FROZEN',json.dumps(counts,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
