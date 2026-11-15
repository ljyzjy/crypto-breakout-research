"""Run the original one-second engine only on alternative-rank extra candidates."""
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
WORK = runner.ROOT / 'zero_hour_extra_tape'


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fingerprint():
    files = [H / '冻结时点.json', H / '替代排名候选质量.json', H / '替代排名候选独立核验.json',
             Path(__file__), R90 / 'replay_2022.py', R90 / '二零二二候选独立核验总表.json']
    return hashlib.sha256(''.join(sha(x) for x in files).encode()).hexdigest()


def main():
    runner.guard(start=True)
    quality = json.loads((H / '替代排名候选质量.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '替代排名候选独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['candidate_quality_sha256'] == sha(H / '替代排名候选质量.json')
    assert audit['code_sha256'] == sha(H / 'audit_extra_candidates.py')
    data_path = H / '替代口径候选/新增潜在触价.parquet'
    assert quality['candidate_sha256'] == sha(data_path)
    sources = runner.verify_inputs()
    format_check = runner.install_header_compatible_reader()
    assert format_check['all_checks_pass']
    data = pd.read_parquet(data_path)
    assert len(data) == quality['extra_candidates'] and data.observation_id.is_unique
    groups = [(sym, day, g.to_dict('records')) for (sym, day), g in data.groupby(['contract', 'day'], sort=True)]
    fp = fingerprint(); WORK.mkdir(parents=True, exist_ok=True); runner.WORK = WORK
    current, norm, done, errors = None, None, 0, []
    print('EXT94_START', len(groups), 'groups', len(data), 'extra candidates', flush=True)
    for sym, day, events in groups:
        try:
            runner.guard()
            if sym != current:
                norm = pd.read_parquet(sources[sym]['path'], columns=['ts', 'open', 'high', 'low', 'close']).set_index('ts')
                assert norm.index.is_unique; current = sym
            result = runner.execute(fp, sym, day, events, norm)
        except Exception as exc:
            result = {'status': 'error', 'contract': sym, 'day': day, 'error': type(exc).__name__ + ':' + str(exc)[:180]}
        if result['status'] == 'verified': done += 1
        else: errors.append({k: result[k] for k in ('contract', 'day', 'error')})
        print('EXT94_GROUP', done, '/', len(groups), 'errors', len(errors), sym, day, result['status'], flush=True)
        if result['status'] != 'verified' and 'headroom' in result['error']: break
    progress = {'total_candidates': len(data), 'total_groups': len(groups), 'completed_groups': done,
                'errors': errors, 'fingerprint': fp, 'code_sha256': sha(Path(__file__)),
                'note': 'Alternative-rank replay checkpoints; risk and independent audit remain outstanding.'}
    (H / '新增候选逐笔回放进度.json').write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_STOP', json.dumps(progress, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
