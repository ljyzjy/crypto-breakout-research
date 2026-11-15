"""Independently reread selected new candidate tapes and scalar replay their paths."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import replay_extra as extra

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
R62 = H.parent / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(R90)); import audit_tapes_2022 as independent
sys.path.insert(0, str(R62)); import audit_tape_samples as scalar


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    extra.runner.guard(start=True)
    test = json.loads((R62 / '独立重放合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['audit_code_sha256'] == sha(R62 / 'audit_tape_samples.py')
    progress = json.loads((H / '新增候选逐笔回放进度.json').read_text(encoding='utf-8'))
    fp = extra.fingerprint(); assert progress['fingerprint'] == fp
    data = pd.read_parquet(H / '替代口径候选/新增潜在触价.parquet')
    known = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}
    available = []
    for (sym, day), group in data.groupby(['contract', 'day'], sort=True):
        events = group.to_dict('records')
        p = extra.WORK / (extra.runner.key(fp, sym, day, events) + '.json')
        if not p.exists(): continue
        cp = json.loads(p.read_text(encoding='utf-8')); assert cp['status'] == 'verified' and cp['fingerprint'] == fp
        rows = {x['observation_id']: x for x in cp['rows']}
        for event in events:
            row = rows[event['observation_id']]
            if row['status'] in known: available.append((event, cp, row))
    available.sort(key=lambda x: (sum(a.get('bytes', 0) for a in x[1]['archives'] if a['kind'] == 'aggTrades'), x[0]['observation_id']))
    chosen, ids = [], set()
    for status in ('qualified', 'flow_filter_not_met', 'known_risk_rejected', 'first_direction_ineligible', 'no_order_time'):
        item = next((x for x in available if x[2]['status'] == status and x[0]['observation_id'] not in ids), None)
        if item: chosen.append(item); ids.add(item[0]['observation_id'])
        if len(chosen) == 3: break
    ext, ext_path = independent.load_extended_scalar()
    samples = []
    for e, cp, row in chosen:
        extra.runner.guard()
        body, bar = extra.runner.minutes.archive('klines', e['contract'], e['day'])
        assert bar['sha256'] == next(x['sha256'] for x in cp['archives'] if x['kind'] == 'klines')
        bars = independent.independent_bars(body, e['day']); del body
        frames, archives = [], []
        for a in (x for x in cp['archives'] if x['kind'] == 'aggTrades'):
            path = independent.download(e['contract'], a)
            frame = independent.scalar_parse(path, int(e['trigger_minute']), int(e['quarter_end']) + 900000 + 60000)
            if len(frame): frames.append(frame)
            archives.append({'day': a['day'], 'sha256': a['sha256'], 'bytes': a['bytes']})
        assert frames
        tape = pd.concat(frames, ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
        checked = scalar.replay(e, tape, bars, row); extended = 0
        for variant, old in row.get('paths', {}).items():
            new = row['extended_paths'][variant]
            if old['status'] == 'verified' and old['reason'] == 'quarter_time' and new['status'] == 'verified':
                ext.scalar_extended({**old, 'side': row['side'], 'quarter_end': e['quarter_end']}, tape, new); extended += 1
            elif old['status'] == 'verified' and old['reason'] != 'quarter_time': assert old == new
        samples.append({'observation_id': e['observation_id'], 'status': row['status'], 'paths_checked': checked,
                        'extended_paths_checked': extended, 'archives': archives})
        print('EXT94_TAPE_SAMPLE', len(samples), '/', len(chosen), flush=True)
    result = {'all_checks_pass': True, 'samples': samples, 'available_known_candidates': len(available),
              'candidate_count': len(data), 'fingerprint': fp, 'code_sha256': sha(Path(__file__)),
              'scalar_sha256': sha(R62 / 'audit_tape_samples.py'), 'csv_reader_sha256': sha(R90 / 'audit_tapes_2022.py'),
              'extended_scalar_sha256': sha(ext_path), 'note': 'Sample only; source mismatch and missing archives remain unknown.'}
    (H / '新增候选逐笔独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_TAPE_AUDIT', len(samples), 'samples', flush=True)


if __name__ == '__main__':
    main()
