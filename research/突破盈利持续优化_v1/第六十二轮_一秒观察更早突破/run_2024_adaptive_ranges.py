"""Resume with the original range reader only while memory headroom permits."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import psutil
import run_observation as runner

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
TAPE = ROOT / 'work/oneobs62_2024/tape'
JOURNAL = H / '2024自适应分段运行记录.jsonl'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def append(row):
    with JOURNAL.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def main():
    test_path = H / '2024自适应分段读取核验.json'
    test = json.loads(test_path.read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['fingerprint'] == runner.fingerprint('2024')
    assert test['plan_sha256'] == sha(H / '2024自适应分段读取方案.md')
    assert test['test_sha256'] == sha(H / 'test_2024_adaptive_ranges.py')
    assert test['runner_sha256'] == sha(H / 'run_observation.py')
    assert test['range_sha256'] == sha(Path(runner.public_range.__file__))
    recovery = json.loads((H / '2024中断后检查点核验.json').read_text(encoding='utf-8'))
    assert recovery['all_checks_pass'] and recovery['fingerprint'] == runner.fingerprint('2024')
    assert recovery['audit_code_sha256'] == sha(H / 'verify_2024_interrupted_checkpoints.py')
    assert all((TAPE / name).is_file() and sha(TAPE / name) == digest for name, digest in recovery['checkpoint_hashes'].items())
    if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 850 * 1024 ** 2:
        raise RuntimeError('startup_headroom')
    TAPE.mkdir(parents=True, exist_ok=True)
    before = {p.name: sha(p) for p in TAPE.glob('*.json')}
    ident = {'started_utc': datetime.now(timezone.utc).isoformat(), 'wrapper_sha256': sha(Path(__file__)),
             'test_sha256': sha(test_path), 'runner_fingerprint': runner.fingerprint('2024'),
             'existing_checkpoints': before, 'max_buffer': 50_000_000, 'workers': 2, 'guards_unchanged': True}
    append({'event': 'start', **ident})
    orig = runner.public_range.fetch
    runner.public_range.WORKERS = 2

    def adaptive(*args, **kwargs):
        runner.public_range.MAX_BUFFER = 50_000_000 if psutil.virtual_memory().available >= 1536 * 1024 ** 2 else 0
        return orig(*args, **kwargs)

    runner.public_range.fetch = adaptive
    try:
        runner.main('2024')
    finally:
        after = {p.name: sha(p) for p in TAPE.glob('*.json')}
        assert all(after.get(k) == v for k, v in before.items())
        append({'event': 'end', 'started_utc': ident['started_utc'], 'ended_utc': datetime.now(timezone.utc).isoformat(),
                'new_checkpoints': {k: v for k, v in after.items() if k not in before}})


if __name__ == '__main__':
    main()
