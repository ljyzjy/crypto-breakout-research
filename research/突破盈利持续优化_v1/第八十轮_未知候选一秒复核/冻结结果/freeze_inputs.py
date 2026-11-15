import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    result = H / '冻结时点.json'
    assert not result.exists()
    previous = P / '第五十四轮_原始成交缺口敏感性' / 'XRP原始成交独立复核与敏感性.json'
    source = json.loads(previous.read_text(encoding='utf-8'))
    test = json.loads((H / '首秒边界测试.json').read_text(encoding='utf-8'))
    assert source['all_checks_pass'] and test['all_checks_pass']
    assert test['code_sha256'] == sha(H / 'one_second_check.py') and test['test_sha256'] == sha(H / 'test_one_second_check.py')
    items = {'plan_sha256': sha(H / '冻结方案.md'), 'previous_source_audit_sha256': sha(previous),
             'baseline_2024_manifest_sha256': sha(P / '第六十二轮_一秒观察更早突破/2024输入冻结哈希.json'),
             'baseline_2024_result_sha256': sha(P / '第六十二轮_一秒观察更早突破/2024完整批次_冻结/完整快照哈希.json'),
             'one_second_engine_sha256': sha(P / '第六十二轮_一秒观察更早突破/one_second_observation.py'),
             'causal_check_sha256': sha(H / 'one_second_check.py'), 'causal_test_sha256': sha(H / '首秒边界测试.json'),
             'prior_official_archive_sha256': {a['kind']: a['sha256'] for a in source['archives']},
             'frozen_utc': datetime.now(timezone.utc).isoformat(),
             'note': 'Fixed before the one-second source outcome; retrospective single-case sensitivity.'}
    result.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    print('UNKNOWN_ONESEC_FREEZE', sha(result), flush=True)


if __name__ == '__main__':
    main()
