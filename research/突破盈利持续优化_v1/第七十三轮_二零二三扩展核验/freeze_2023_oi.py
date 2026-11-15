"""Freeze the independently checked 2023 OI comparison."""
import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    point = json.loads((H / '2023持仓量逐点核验.json').read_text(encoding='utf-8'))
    source = json.loads((H / '2023持仓量来源独立核验.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '2023持仓量门独立核验.json').read_text(encoding='utf-8'))
    result_path = H / '2023持仓量跨期对照.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert source['all_checks_pass'] and source['point_input_sha256'] == sha(H / '2023持仓量逐点核验.json')
    assert audit['all_checks_pass'] and audit['groups_checked'] == 12 and audit['result_sha256'] == sha(result_path)
    assert result['original_unknown_candidates'] == 19 and len(result['rows']) == 12
    assert all(x['unknown_candidates'] >= 19 and x['known_trades'] + x['known_no_order'] + x['unknown_candidates'] == 146 for x in result['rows'])
    names = ['冻结研究方案.md', '冻结时点.json', 'prepare_2023_oi.py', '2023持仓量逐点核验.json', 'audit_2023_oi_sources.py', '2023持仓量来源独立核验.json',
             '2023一秒观察已核验账本.csv', 'evaluate_2023_oi.py', '2023一秒观察持仓量逐笔.csv',
             '2023持仓量跨期对照.json', 'audit_2023_oi.py', '2023持仓量门独立核验.json', 'freeze_2023_oi.py']
    dest = H / '2023持仓量冻结结果'
    dest.mkdir(exist_ok=True)
    files = {}
    for name in names:
        source, target = H / name, dest / name
        digest = sha(source)
        if target.exists():
            assert sha(target) == digest
        else:
            shutil.copyfile(source, target)
            assert sha(target) == digest
        files[name] = digest
    out = {'all_checks_pass': True, 'year': '2023', 'all_oi_points_and_samples_verified': point['all_checks_pass'],
           'official_sample_errors': point['official_errors'], 'files': files,
           'note': 'Exploratory historical comparison; cannot establish live OI timing, actual fills, or account results.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('YEAR2023_OI_FREEZE', len(files), flush=True)


if __name__ == '__main__':
    main()
