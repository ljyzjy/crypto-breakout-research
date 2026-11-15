"""Test existing ranged ZIP transport against two saved 2024 outcomes."""
import hashlib
import json
import shutil
import uuid
from pathlib import Path

import psutil
import run_observation as runner
from test_2024_stream_reader import same

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 1536 * 1024 ** 2:
        raise RuntimeError('startup_headroom')
    candidates, baseline, paths, proof = runner.inputs('2024')
    fp = runner.fingerprint('2024')
    current = ROOT / 'work/oneobs62_2024/tape'
    isolated = ROOT / 'work' / ('oneobs62_2024_range_parity_' + uuid.uuid4().hex) / 'tape'
    isolated.mkdir(parents=True, exist_ok=False)
    candidates = candidates[candidates.observation_id.isin(proof)]
    choices = []
    for (sym, day, n), group in candidates.groupby(['contract', 'day', 'needs_next']):
        spec = (sym, day, bool(n), group.to_dict('records'))
        path = current / (runner.key(fp, spec) + '.json')
        if not path.exists():
            continue
        cp = json.loads(path.read_text(encoding='utf-8'))
        size = sum(int(a.get('bytes', 0)) for a in cp['archives'] if a['kind'] == 'aggTrades')
        choices.append((size, spec, path, cp))
    choices.sort(key=lambda x: (x[0], str(x[2])))
    selected = []
    for status in ('qualified', 'flow_filter_not_met'):
        item = next((x for x in choices if any(r['status'] == status for r in x[3]['rows']) and x[2] not in {a[2] for a in selected}), None)
        assert item is not None
        selected.append(item)
    runner.public_range.MAX_BUFFER = 50_000_000
    runner.public_range.WORKERS = 2
    checked = []
    for _, spec, path, original in selected:
        fresh = runner.task('2024', fp, spec, baseline, paths, proof, isolated)
        assert fresh['status'] == original['status'] == 'verified'
        for name in ('contract', 'day', 'needs_next', 'rows'):
            assert same(original[name], fresh[name]), (path.name, name)
        def arch(z):
            return [{k: a.get(k) for k in ('kind', 'day', 'sha256', 'bytes', 'windows')} for a in z['archives']]
        assert same(arch(original), arch(fresh))
        assert any(x.get('reader') == 'sha256_verified_http_ranges' for x in fresh['archives'])
        checked.append({'contract': spec[0], 'day': spec[1], 'statuses': [x['status'] for x in original['rows']],
                        'old_checkpoint_sha256': sha(path), 'new_checkpoint_sha256': sha(isolated / path.name)})
        print('OBS62_RANGE_PARITY', len(checked), '/2', flush=True)
    result = {'all_checks_pass': True, 'fingerprint': fp, 'plan_sha256': sha(H / '2024自适应分段读取方案.md'),
              'test_sha256': sha(Path(__file__)), 'range_sha256': sha(Path(runner.public_range.__file__)),
              'runner_sha256': sha(H / 'run_observation.py'), 'samples': checked,
              'note': 'Independent rereads; compare decisions and complete source hashes, not execution speed.'}
    (H / '2024自适应分段读取核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OBS62_RANGE_PARITY_PASS', len(checked), flush=True)


if __name__ == '__main__':
    main()
