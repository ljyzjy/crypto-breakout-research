import hashlib
import json
from pathlib import Path

from extension_gate import gate

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    event = {'side': 1, 'level': '100', 'raw_entry_1s': '100.05', 'decision_ts': 0, 'entry_exec_ts': 1000}
    assert gate(event)[0] is True  # exactly 0.05% is allowed
    assert gate({**event, 'raw_entry_1s': '100.050001'})[0] is False
    assert gate({**event, 'raw_entry_1s': '100'})[0] is False
    assert gate({**event, 'side': -1, 'raw_entry_1s': '99.95'})[0] is True
    assert gate({**event, 'side': -1, 'raw_entry_1s': '99.949999'})[0] is False
    assert gate({**event, 'entry_exec_ts': 999})[0] is None
    assert gate({**event, 'level': 0})[0] is None
    assert gate({**event, 'future_high': 1e100, 'future_close': -1e100, 'net': -1e100}) == gate(event)
    out = {'all_checks_pass': True, 'checks': ['long_short', 'strict_cross', 'inclusive_limit', 'one_second_boundary',
           'invalid_price_unknown', 'future_perturbation'], 'gate_sha256': sha(H / 'extension_gate.py'),
           'test_code_sha256': sha(Path(__file__))}
    (H / '追价距离合成核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT86_TEST', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
