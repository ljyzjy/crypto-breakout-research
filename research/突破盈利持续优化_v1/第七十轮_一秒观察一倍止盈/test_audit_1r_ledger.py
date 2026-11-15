"""Check independent ledger auditing against one prior verified path and tampering."""
import hashlib
import json
from pathlib import Path
import shutil
import uuid

import pyarrow.parquet as pq
import audit_1r_ledger as audit
import settle_1r_local as settlement

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    snap = settlement.P / '第六十二轮_一秒观察更早突破/2026完整批次_冻结'
    manifest = json.loads((snap / '完整快照哈希.json').read_text(encoding='utf-8'))
    name = 'batch/动态池单位收益与风险.parquet'
    assert sha(snap / name) == manifest['files'][name]
    rows = pq.read_table(snap / name).to_pylist()
    row = next(x for x in rows if x['contract'] == 'AVAXUSDT' and settlement.month(x['entry_ts']) == '2026-05' and x['risk_status'] == 'verified')
    required = {('AVAXUSDT', '2026-05'): set(range(row['entry_ts'] // 60000 * 60000, row['exit_ts'] // 60000 * 60000 + 60000, 60000))}
    sources = json.loads((snap / 'batch/动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    expected = {(x['kind'], x['contract'], x['month']): x for x in sources}
    _, _, _, archives = settlement.load_risk('2026', required, expected)
    assert all(x['status'] == 'verified' for x in archives)
    row['variant'] = row['variant'].replace('_2r_', '_1r_')
    scratch = settlement.ROOT / 'work' / ('oneobs1r70_audit_test_' + uuid.uuid4().hex)
    scratch.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(H / 'settle_1r_local.py', scratch / 'settle_1r_local.py')
    payload = {'year': '2026', 'settlement_code_sha256': sha(H / 'settle_1r_local.py'),
               'records': [row], 'risk_archives': archives, 'replay_unknown': []}
    fixture = scratch / '2026一倍止盈本地风险账本.json'
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    audit.H = scratch
    audit.main('2026')
    result = json.loads((scratch / '2026一倍止盈账本独立核验.json').read_text(encoding='utf-8'))
    assert result['all_checks_pass'] and result['audited_paths'] == 1
    payload['records'][0]['net_per_unit_notional'] += .01
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    try:
        audit.main('2026')
    except AssertionError:
        changed_detected = True
    else:
        raise AssertionError('tampered net return was not detected')
    out = {'all_checks_pass': True, 'verified_prior_path_matches': True, 'tampered_return_rejected': changed_detected,
           'audit_code_sha256': sha(H / 'audit_1r_ledger.py'), 'settlement_code_sha256': sha(H / 'settle_1r_local.py'),
           'test_code_sha256': sha(Path(__file__)), 'note': 'The test reuses an old verified 2R path; it is not an observed 1R result.'}
    (H / '一倍止盈账本核验合成测试.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_1R_LEDGER_SYNTHETIC_PASS', flush=True)


if __name__ == '__main__':
    main()
