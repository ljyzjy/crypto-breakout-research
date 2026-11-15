"""Copy causal inputs and prior verified sample before the buffer comparison."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent/'第四十轮_BTC_ETH事前活跃度';D=H/'冻结输入';D.mkdir(exist_ok=True)
files={'signal.parquet':P/'冻结输入'/'baseline_signal.parquet','ledger.parquet':P/'冻结输入'/'baseline_ledger.parquet',
       'market_decisions.parquet':P/'候选事前市场过滤.parquet','dual_result.json':P/'双币活跃度训练诊断.json',
       'dual_audit.json':P/'双币活跃度独立核验.json'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
out={'plan_sha256':sha(H/'冻结研究方案.md'),'files':{}}
for name,src in files.items():
    dst=D/name;v=sha(src)
    if dst.exists():assert sha(dst)==v
    else:shutil.copy2(src,dst)
    assert sha(dst)==v;out['files'][name]=v
p=H/'输入冻结哈希.json'
if p.exists():assert json.loads(p.read_text(encoding='utf-8'))==out
else:p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('BUFFER41_INPUTS_FROZEN',len(files),flush=True)
