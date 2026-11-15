"""Verify preserved checkpoints after interrupting a stalled transport."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import run_observation as runner

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    lines = (H / '2024低内存顺序读取运行记录.jsonl').read_text(encoding='utf-8').splitlines()
    start = next(json.loads(x) for x in reversed(lines) if json.loads(x)['event'] == 'start')
    cand, _, _, proof = runner.inputs('2024')
    fp = runner.fingerprint('2024')
    assert fp == start['runner_fingerprint']
    cand = cand[cand.observation_id.isin(proof)]
    expected = {runner.key(fp, (s, day, bool(n), g.to_dict('records'))) for (s, day, n), g in cand.groupby(['contract', 'day', 'needs_next'])}
    folder = ROOT / 'work/oneobs62_2024/tape'
    files = list(folder.glob('*.json'))
    assert len({p.name for p in files}) == len(files) and all(p.stem in expected for p in files)
    hashes = {}
    for p in files:
        cp = json.loads(p.read_text(encoding='utf-8'))
        assert cp['status'] == 'verified'
        hashes[p.name] = sha(p)
    assert all(hashes.get(name) == value for name, value in start['existing_checkpoints'].items())
    out = {'all_checks_pass': True, 'checked_utc': datetime.now(timezone.utc).isoformat(), 'fingerprint': fp,
           'verified_checkpoints': len(files), 'unchanged_at_previous_start': len(start['existing_checkpoints']),
           'checkpoint_hashes': hashes, 'audit_code_sha256': sha(Path(__file__)),
           'note': 'The stalled stream process was interrupted; it did not write a normal end journal. Completed checkpoint hashes and valid task keys were checked.'}
    (H / '2024中断后检查点核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OBS62_RECOVERY_PASS', len(files), len(start['existing_checkpoints']), flush=True)


if __name__ == '__main__':
    main()
