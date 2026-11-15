"""Snapshot the already-observed 2023 records before post-close capture analysis."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent/'第四十三轮_旧十一币2023年复核';I=H/'冻结输入';I.mkdir(exist_ok=True)
sources={'candidates.parquet':P/'2023双币过滤潜在触价.parquet',
         'signals.parquet':P/'部分批次'/'动态池逐笔信号筛查.parquet',
         'ledger.parquet':P/'部分批次'/'动态池单位收益与风险.parquet',
         'risk_quality.json':P/'部分批次'/'动态池单位筛查完整性.json',
         'minute_hashes.json':P/'来源冻结哈希.json',
         'ledger_audit.json':P/'部分批次'/'2023净账本独立核验.json'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=H/'冻结输入哈希.json'
    if out.exists():
        f=json.loads(out.read_text(encoding='utf-8'));assert f['plan_sha256']==sha(H/'事后诊断方案.md')
        for n,v in f['inputs'].items():assert sha(I/n)==v
        return
    for n,src in sources.items():
        dest=I/n
        if dest.exists():assert sha(dest)==sha(src)
        else:shutil.copy2(src,dest)
        assert sha(dest)==sha(src)
    assert json.loads((I/'ledger_audit.json').read_text(encoding='utf-8'))['independently_checked_verified_paths']==168
    f={'plan_sha256':sha(H/'事后诊断方案.md'),'inputs':{n:sha(I/n) for n in sources},
       'note':'Analysis was planned after historical 2023 unit results were observed.'}
    out.write_text(json.dumps(f,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE45_INPUTS_FROZEN',len(sources),flush=True)
if __name__=='__main__':main()
