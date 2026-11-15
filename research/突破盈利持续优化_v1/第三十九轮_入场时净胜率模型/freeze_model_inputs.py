"""Snapshot model training and candidate inputs before validation scoring."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;OUT=H/'冻结输入';OUT.mkdir(exist_ok=True)
src=P/'第三十三轮_动态池逐笔执行';prior=P/'第三十八轮_大突破柱捕捉诊断'/'冻结输入'
files={'train_signal.parquet':prior/'baseline_signal.parquet','train_ledger.parquet':prior/'baseline_ledger.parquet',
       'train_quality.json':prior/'baseline_quality.json','all_signal.parquet':src/'动态池逐笔信号筛查.parquet',
       'all_paths.parquet':src/'动态池延迟市价路径.parquet','all_quality.json':src/'动态池逐笔提取质量.json'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
out={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{}}
for name,path in files.items():
    dst=OUT/name;v=sha(path)
    if dst.exists():assert sha(dst)==v
    else:shutil.copy2(path,dst)
    assert sha(dst)==v;out['inputs'][name]={'source':str(path),'sha256':v}
p=H/'输入冻结哈希.json'
if p.exists():assert json.loads(p.read_text(encoding='utf-8'))==out
else:p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('NETMODEL39_INPUTS_FROZEN',len(files),flush=True)
