"""Freeze verified one-second entry paths and their risk evidence."""
import hashlib,json,shutil
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;FAST=P/'第五十一轮_缩短市价入场延迟'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    test=json.loads((H/'组合合成时序核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256']==sha(H/'early_1r.py') and test['plan_sha256']==sha(H/'冻结研究方案.md')
    for year in ('2024','2026'):
        dest=H/f'{year}冻结输入';manifest=H/f'{year}输入冻结哈希.json'
        assert not dest.exists() and not manifest.exists();dest.mkdir()
        source=FAST/f'{year}冻结输入';batch=FAST/f'{year}一秒入场分批'
        upstream=json.loads((FAST/f'{year}输入冻结哈希.json').read_text(encoding='utf-8'))
        assert upstream['plan_sha256']==sha(FAST/'冻结研究方案.md')
        assert all(sha(source/n)==v for n,v in upstream['inputs'].items())
        expected=93 if year=='2024' else 28
        qa=json.loads((batch/'动态池单位筛查完整性.json').read_text(encoding='utf-8'))
        audit=json.loads((FAST/f'{year}一秒入场账本独立核验.json').read_text(encoding='utf-8'))
        sample=json.loads((FAST/f'{year}一秒入场逐笔独立抽查.json').read_text(encoding='utf-8'))
        assert qa['complete'] and qa['verified_tape_paths']==expected and qa['ledger_paths']==expected
        assert qa['source_paths_sha256']==sha(batch/'动态池延迟市价路径.parquet')
        assert audit['all_checks_pass'] and audit['audited_one_second_paths']==expected and sample['all_checks_pass']
        files={'events.parquet':source/'qualified_entries.parquet',
            'paths_2r.parquet':batch/'动态池延迟市价路径.parquet','ledger_2r.parquet':batch/'动态池单位收益与风险.parquet',
            'signal.parquet':batch/'动态池逐笔信号筛查.parquet','quality.json':batch/'动态池逐笔提取质量.json',
            'risk_quality.json':batch/'动态池单位筛查完整性.json','risk_manifest.json':batch/'动态池风险档案核验清单.json',
            'execution.json':batch/'逐笔执行冻结方案.json','pair_summary.json':FAST/f'{year}一秒五秒配对对照.json',
            'pair_details.parquet':FAST/f'{year}一秒五秒逐笔配对结果.parquet',
            'ledger_audit.json':FAST/f'{year}一秒入场账本独立核验.json','sample_audit.json':FAST/f'{year}一秒入场逐笔独立抽查.json',
            'upstream_frozen.json':FAST/f'{year}输入冻结哈希.json'}
        for name,src in files.items():shutil.copy2(src,dest/name);assert sha(src)==sha(dest/name)
        record={'year':year,'plan_sha256':sha(H/'冻结研究方案.md'),'code_sha256':sha(H/'early_1r.py'),
                'inputs':{name:sha(dest/name) for name in files},'sources':{name:str(path) for name,path in files.items()}}
        manifest.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print('EARLY_1R_FROZEN',year,len(files),'paths',expected,flush=True)
if __name__=='__main__':main()
