"""Freeze only existing research inputs before calculating large-bar labels."""
import hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent;P=HERE.parent;OUT=HERE/'冻结输入';OUT.mkdir(exist_ok=True)
inputs={
 'baseline_signal.parquet':P/'第三十三轮_动态池逐笔执行'/'训练期分批'/'动态池逐笔信号筛查.parquet',
 'baseline_paths.parquet':P/'第三十三轮_动态池逐笔执行'/'训练期分批'/'动态池延迟市价路径.parquet',
 'baseline_ledger.parquet':P/'第三十三轮_动态池逐笔执行'/'训练期分批'/'动态池单位收益与风险.parquet',
 'baseline_quality.json':P/'第三十三轮_动态池逐笔执行'/'训练期分批'/'动态池单位筛查完整性.json',
 'follow_signal.parquet':P/'第三十五轮_二次价格跟随'/'训练期分批'/'动态池逐笔信号筛查.parquet',
 'follow_paths.parquet':P/'第三十五轮_二次价格跟随'/'训练期分批'/'动态池延迟市价路径.parquet',
 'follow_ledger.parquet':P/'第三十五轮_二次价格跟随'/'训练期分批'/'动态池单位收益与风险.parquet',
 'follow_quality.json':P/'第三十五轮_二次价格跟随'/'训练期分批'/'动态池单位筛查完整性.json',
 'phase_result.json':P/'第三十六轮_避开整点首十秒'/'首十秒过滤训练诊断.json'
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
manifest={'plan_sha256':sha(HERE/'事后诊断方案.md'),'sources':{}}
for name,src in inputs.items():
    dest=OUT/name;digest=sha(src)
    if dest.exists():assert sha(dest)==digest,('existing_snapshot_conflict',name)
    else:shutil.copy2(src,dest)
    assert sha(dest)==digest
    manifest['sources'][name]={'source':str(src),'sha256':digest}
assert manifest['sources']['baseline_signal.parquet']['sha256']==sha(P/'第三十六轮_避开整点首十秒'/'冻结输入'/'动态池逐笔信号筛查.parquet')
assert manifest['sources']['baseline_ledger.parquet']['sha256']==sha(P/'第三十六轮_避开整点首十秒'/'冻结输入'/'动态池单位收益与风险.parquet')
path=HERE/'冻结输入哈希.json'
if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==manifest
else:path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('CAPTURE38_INPUTS_FROZEN',len(inputs),flush=True)
