"""Freeze the audited 2024 one-second OI gate before subsequent studies."""
import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent
DEST = H / '2024冻结结果'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    point = json.loads((H / '2024持仓量逐点核验.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '2024持仓量门独立核验.json').read_text(encoding='utf-8'))
    result = json.loads((H / '2024一秒观察持仓量对照.json').read_text(encoding='utf-8'))
    assert point['plan_sha256'] == sha(H / '冻结研究方案.md') and audit['all_checks_pass']
    assert audit['result_sha256'] == sha(H / '2024一秒观察持仓量对照.json') and audit['groups_checked'] == 12
    assert len(result['rows']) == 12 and result['original_unknown_candidates'] == 16
    assert all(r['unknown_candidates'] >= 16 and r['known_trades'] + r['known_no_order'] + r['unknown_candidates'] == 119 for r in result['rows'])
    names = ['冻结研究方案.md', 'prepare_2024_oi_points.py', 'evaluate_2024_oi_gate.py', 'audit_2024_oi_gate.py',
             '2024持仓量逐点核验.json', '2024一秒观察已核验账本.csv', '2024一秒观察持仓量对照.json',
             '2024一秒观察持仓量逐笔.csv', '2024持仓量门独立核验.json']
    files = {}
    DEST.mkdir(parents=True, exist_ok=True)
    for name in names:
        src, dst = H / name, DEST / name
        digest = sha(src)
        if dst.exists():
            assert sha(dst) == digest
        else:
            shutil.copyfile(src, dst)
            assert sha(dst) == digest
        files[name] = digest
    out = {'all_checks_pass': True, 'year': '2024', 'files': files,
           'all_oi_points_verified': point['all_checks_pass'], 'official_archive_errors': point['official_errors'],
           'note': 'Exploratory historical comparison; unknown sources and real-time OI availability remain unresolved.'}
    (DEST / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_OI_2024_FREEZE', len(files), 'files', flush=True)


if __name__ == '__main__':
    main()
