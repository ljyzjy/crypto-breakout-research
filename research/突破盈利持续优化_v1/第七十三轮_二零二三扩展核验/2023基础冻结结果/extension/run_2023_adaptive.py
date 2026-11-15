"""Run the frozen 2023 one-second replay with guarded ranged ZIP transport."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

import psutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
R62 = P / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(R62))
import run_observation as runner


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def append(row):
    with (H / '2023续跑记录.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == frozen['plan_sha256']
    assert runner.fingerprint('2023') == frozen['runner_fingerprint']
    assert sha(R62 / '2023输入冻结哈希.json') == frozen['prior_input_manifest_sha256']
    assert sha(P / '第六十九轮_一秒观察持仓量门/冻结研究方案.md') == frozen['oi_plan_sha256']
    test = json.loads((R62 / '2024自适应分段读取核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and len(test['samples']) == 2
    assert test['range_sha256'] == sha(Path(runner.public_range.__file__)) and test['runner_sha256'] == sha(R62 / 'run_observation.py')
    stream = json.loads((R62 / '2024低内存顺序读取核验.json').read_text(encoding='utf-8'))
    assert stream['all_checks_pass'] and stream['stream_sha256'] == sha(P / '第四十七轮_一次重新突破确认/public_tape_stream.py')
    if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 850 * 1024 ** 2:
        raise RuntimeError('startup_headroom')
    folder = ROOT / 'work/oneobs62_2023/tape'
    folder.mkdir(parents=True, exist_ok=True)
    before = {p.name: sha(p) for p in folder.glob('*.json')}
    ident = {'started_utc': datetime.now(timezone.utc).isoformat(), 'wrapper_sha256': sha(Path(__file__)),
             'fingerprint': frozen['runner_fingerprint'], 'existing_checkpoints': before,
             'range_parity_sha256': sha(R62 / '2024自适应分段读取核验.json'), 'guards_unchanged': True}
    append({'event': 'start', **ident})
    orig = runner.public_range.fetch
    runner.public_range.WORKERS = 2

    def adaptive(*args, **kwargs):
        runner.public_range.MAX_BUFFER = 50_000_000 if psutil.virtual_memory().available >= 1536 * 1024 ** 2 else 0
        return orig(*args, **kwargs)

    runner.public_range.fetch = adaptive
    try:
        runner.main('2023')
    finally:
        after = {p.name: sha(p) for p in folder.glob('*.json')}
        assert all(after.get(k) == v for k, v in before.items())
        append({'event': 'end', 'started_utc': ident['started_utc'], 'ended_utc': datetime.now(timezone.utc).isoformat(),
                'new_checkpoints': {k: v for k, v in after.items() if k not in before}})


if __name__ == '__main__':
    main()
