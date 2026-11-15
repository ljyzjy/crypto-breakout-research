"""Freeze 2023 baseline inputs and identify causal, no-order retry candidates."""
import hashlib,json,shutil
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent/'第四十三轮_旧十一币2023年复核';I=H/'2023冻结输入';I.mkdir(exist_ok=True)
sources={'candidates.parquet':P/'2023双币过滤潜在触价.parquet',
         'baseline_signal.parquet':P/'部分批次'/'动态池逐笔信号筛查.parquet',
         'baseline_paths.parquet':P/'部分批次'/'动态池延迟市价路径.parquet',
         'baseline_ledger.parquet':P/'部分批次'/'动态池单位收益与风险.parquet',
         'baseline_quality.json':P/'部分批次'/'动态池单位筛查完整性.json',
         'baseline_audit.json':P/'部分批次'/'2023净账本独立核验.json',
         'minute_sources.json':P/'来源冻结哈希.json',
         'risk_sources.json':P/'风险来源冻结哈希.json',
         'postclose_labels.parquet':H.parent/'第四十五轮_2023大突破柱捕捉诊断'/'2023候选事后大柱标签.parquet'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=H/'2023输入冻结哈希.json'
    if out.exists():
        f=json.loads(out.read_text(encoding='utf-8'));assert f['plan_sha256']==sha(H/'冻结研究方案.md')
        for n,v in f['inputs'].items():assert sha(I/n)==v
        return
    assert json.loads(sources['baseline_audit.json'].read_text(encoding='utf-8'))['independently_checked_verified_paths']==168
    for n,src in sources.items():
        dst=I/n
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    signal=pd.read_parquet(I/'baseline_signal.parquet')
    chosen=signal[signal.status.eq('flow_filter_not_met')&(signal.side*(signal.raw_entry_5s-signal.level)<=0)].copy()
    assert signal.observation_id.is_unique and chosen.observation_id.is_unique
    chosen.to_parquet(I/'retry_candidates.parquet',index=False)
    f={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{n:sha(I/n) for n in [*sources,'retry_candidates.parquet']},
       'retry_candidates':len(chosen),'groups':len(chosen[['contract','day','needs_next']].drop_duplicates()),
       'note':'Retry selection uses only original no-order status and the first five-second reference, not final candle labels.'}
    out.write_text(json.dumps(f,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_2023_INPUTS_FROZEN',len(chosen),'groups',f['groups'],flush=True)
if __name__=='__main__':main()
