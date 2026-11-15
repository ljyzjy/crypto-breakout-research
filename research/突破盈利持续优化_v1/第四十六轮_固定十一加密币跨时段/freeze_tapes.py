"""Freeze fixed-pool candidates and prior tape snapshots before reuse/replay."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;I=H/'逐笔冻结输入';I.mkdir(exist_ok=True)
O=P/'第三十三轮_动态池逐笔执行';B=P/'第三十四轮_历史候选动态替补'
files={'2024_candidates.parquet':H/'2024'/'固定十一币双币过滤潜在触价.parquet',
       '2026_candidates.parquet':H/'2026'/'固定十一币双币过滤潜在触价.parquet',
       'old_signal.parquet':O/'动态池逐笔信号筛查.parquet','old_paths.parquet':O/'动态池延迟市价路径.parquet',
       'backup_signal.parquet':B/'替补新增逐笔信号.parquet','backup_paths.parquet':B/'替补新增延迟市价路径.parquet',
       'old_quality.json':O/'动态池逐笔提取质量.json','backup_quality.json':B/'替补新增逐笔质量.json',
       'old_execution_plan.json':O/'逐笔执行冻结方案.json','old_reuse_audit.json':B/'共同候选复用独立核验.json',
       'minute_sources.json':H/'小块来源冻结哈希.json'}
for year in (2024,2026):
    for typ,name in [('rank','固定十一币排名独立核验.json'),('events','固定十一币候选独立核验.json'),('market','BTC_ETH行情样本核验.json')]:
        files[f'{year}_{typ}_audit.json']=H/str(year)/name
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    for year in (2024,2026):
        for typ in ('rank','events','market'):
            assert json.loads(files[f'{year}_{typ}_audit.json'].read_text(encoding='utf-8'))['all_checks_pass']
    code={name:{'path':str(p),'sha256':sha(p)} for name,p in {'decision':O/'tape_decision.py','paths':O/'leveraged_paths.py',
          'extract':O/'extract_dynamic_tapes.py'}.items()}
    for name,src in files.items():
        dst=I/name
        if dst.exists():assert sha(dst)==sha(src)
        else:shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
    out={'plan_sha256':sha(H/'冻结研究方案.md'),'inputs':{n:sha(I/n) for n in files},'code':code,
         'note':'Rank and source audits are frozen; exact execution-input parity is required before any tape reuse.'}
    target=H/'逐笔输入冻结哈希.json'
    if target.exists():assert json.loads(target.read_text(encoding='utf-8'))==out
    else:target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_TAPE_INPUTS_FROZEN',len(files),flush=True)
if __name__=='__main__':main()
