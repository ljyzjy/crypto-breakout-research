"""Materialize every alternative-rank candidate and keep missing checkpoints unknown."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import replay_extra as extra

H = Path(__file__).resolve().parent
B = H / '一秒回放批次'
BENIGN = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    extra.runner.guard(start=True)
    progress = json.loads((H / '新增候选逐笔回放进度.json').read_text(encoding='utf-8'))
    fp = extra.fingerprint(); assert progress['fingerprint'] == fp and progress['code_sha256'] == sha(H / 'replay_extra.py')
    data = pd.read_parquet(H / '替代口径候选/新增潜在触价.parquet')
    records, archives = {}, []
    for (sym, day), group in data.groupby(['contract', 'day'], sort=True):
        events = group.to_dict('records')
        path = extra.WORK / (extra.runner.key(fp, sym, day, events) + '.json')
        if not path.exists():
            for e in events: records[e['observation_id']] = {'status': 'archive_pending'}
            continue
        cp = json.loads(path.read_text(encoding='utf-8'))
        assert cp['fingerprint'] == fp and cp['status'] == 'verified'
        assert {x['observation_id'] for x in cp['rows']} == set(group.observation_id)
        archives.append({'contract': sym, 'day': day, 'checkpoint_sha256': sha(path), 'archives': cp['archives']})
        for x in cp['rows']:
            assert x['observation_id'] not in records
            records[x['observation_id']] = x
    assert set(records) == set(data.observation_id)
    sigs, paths = [], []
    for e in data.to_dict('records'):
        row = records[e['observation_id']]; pre = row.get('prechecks', {})
        for holding, name in [('original', 'paths'), ('extended', 'extended_paths')]:
            for variant, p in row.get(name, {}).items():
                paths.append({'observation_id': e['observation_id'], 'holding_rule': holding, 'variant': variant, **p})
        sigs.append({**e, **{k: v for k, v in row.items() if k not in ('prechecks', 'paths', 'extended_paths')},
                     'precheck_10x': pre.get('10'), 'precheck_20x': pre.get('20')})
    signals = pd.DataFrame(sigs) if sigs else data.copy()
    path_df = pd.DataFrame(paths) if paths else pd.DataFrame(columns=['observation_id', 'holding_rule', 'variant', 'status'])
    assert not path_df.duplicated(['observation_id', 'holding_rule', 'variant']).any()
    B.mkdir(exist_ok=True)
    signals.to_parquet(B / '动态池逐笔信号筛查.parquet', index=False)
    path_df.to_parquet(B / '动态池延迟市价路径.parquet', index=False)
    unknown = signals.loc[~signals.status.isin(BENIGN), 'observation_id'].tolist() if len(signals) else []
    quality = {'candidate_events': len(signals), 'event_statuses': signals.status.value_counts().to_dict() if len(signals) else {},
               'unexpected_event_count': len(unknown), 'variant_paths': len(path_df),
               'path_statuses': path_df.status.value_counts().to_dict(), 'archive_errors': [{'events': unknown}] if unknown else [],
               'archives': archives, 'fingerprint': fp, 'code_sha256': sha(Path(__file__)),
               'note': 'Alternative-rank candidates only; raw decisions are not settled risk paths.'}
    (B / '动态池逐笔提取质量.json').write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_BATCH', json.dumps({k: v for k, v in quality.items() if k != 'archives'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
