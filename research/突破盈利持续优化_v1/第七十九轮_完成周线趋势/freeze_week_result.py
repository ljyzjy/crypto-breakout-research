"""Copy the completed, independently audited research artifact into a hash snapshot."""
import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    source = json.loads((H / '已完成周线独立核验.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '周线趋势独立核验.json').read_text(encoding='utf-8'))
    assert source['all_checks_pass'] and audit['all_checks_pass']
    assert source['source_sha256'] == sha(H / '已完成周线来源核验.json')
    assert audit['result_sha256'] == sha(H / '周线趋势跨期对照.json')
    assert audit['detail_sha256'] == sha(H / '周线趋势逐笔.csv')
    names = ['冻结研究方案.md', '冻结时点.json', '周线缺口补充规则.md', '补充规则冻结.json',
             'prepare_weeks.py', 'audit_week_sources.py', 'week_gate.py', 'test_week_gate.py',
             'evaluate_week_gate.py', 'audit_week_gate.py', '已完成周线来源核验.json',
             '已完成周线独立核验.json', '周线时间与边界测试.json', '周线趋势逐笔.csv',
             '周线趋势跨期对照.json', '周线趋势独立核验.json', '完成周线趋势对照结果.md']
    target = H / '冻结结果'
    assert not target.exists()
    target.mkdir()
    for name in names:
        shutil.copy2(H / name, target / name)
        assert sha(H / name) == sha(target / name)
    manifest = {'all_checks_pass': True, 'files': {name: sha(target / name) for name in names},
                'freeze_code_sha256': sha(Path(__file__)),
                'note': 'Frozen retrospective evidence; no independent blind sample or live execution.'}
    (target / '冻结哈希.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WEEK_FREEZE', len(names), sha(target / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
