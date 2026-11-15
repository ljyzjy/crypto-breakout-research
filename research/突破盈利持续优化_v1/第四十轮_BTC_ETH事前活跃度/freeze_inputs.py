"""Snapshot the preexisting training decisions before market-regime results."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;D=H/'冻结输入';D.mkdir(exist_ok=True)
old=P/'第三十八轮_大突破柱捕捉诊断'/'冻结输入'
files=['baseline_signal.parquet','baseline_paths.parquet','baseline_ledger.parquet','baseline_quality.json']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
out={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{}}
for name in files:
    a=old/name;b=D/name;v=sha(a)
    if b.exists():assert sha(b)==v
    else:shutil.copy2(a,b)
    assert sha(b)==v;out['inputs'][name]=v
p=H/'输入冻结哈希.json'
if p.exists():assert json.loads(p.read_text(encoding='utf-8'))==out
else:p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('DUAL40_INPUTS_FROZEN',len(files),flush=True)
