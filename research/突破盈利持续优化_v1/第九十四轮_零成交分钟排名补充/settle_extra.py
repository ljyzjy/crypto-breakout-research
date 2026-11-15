"""Apply the validated 2022 risk engine to additional alternative-rank paths."""
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import settle_risk_2022 as base
import replay_extra as extra


def main():
    extra.runner.guard(start=True)
    proof = json.loads((H / '新增候选逐笔独立核验.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['fingerprint'] == extra.fingerprint()
    assert proof['code_sha256'] == base.sha(H / 'audit_extra_tapes.py')
    base.H, base.B = H, H / '一秒回放批次'
    base.WORK = extra.runner.ROOT / 'zero_hour_extra_risk'
    base.runner.fingerprint = extra.fingerprint
    base.main()
    path = base.B / '风险来源与结算.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    result['wrapper_code_sha256'] = base.sha(Path(__file__))
    result['alternative_candidate_audit_sha256'] = base.sha(H / '替代排名候选独立核验.json')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_RISK_SETTLED', result['verified_tape_paths'], 'paths', flush=True)


if __name__ == '__main__':
    main()
