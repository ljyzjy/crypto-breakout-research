"""Freeze backup-universe training inputs before the dual-market calculation."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent/'第三十四轮_历史候选动态替补'/'训练期分批';D=H/'冻结输入';D.mkdir(exist_ok=True)
files={'baseline_signal.parquet':P/'动态池逐笔信号筛查.parquet','baseline_paths.parquet':P/'动态池延迟市价路径.parquet',
       'baseline_ledger.parquet':P/'动态池单位收益与风险.parquet','baseline_quality.json':P/'动态池单位筛查完整性.json'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
out={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{}}
for name,src in files.items():
    dst=D/name;v=sha(src)
    if dst.exists():assert sha(dst)==v
    else:shutil.copy2(src,dst)
    assert sha(dst)==v;out['inputs'][name]=v
p=H/'输入冻结哈希.json'
if p.exists():assert json.loads(p.read_text(encoding='utf-8'))==out
else:p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('DUAL42_INPUTS_FROZEN',len(files),flush=True)
