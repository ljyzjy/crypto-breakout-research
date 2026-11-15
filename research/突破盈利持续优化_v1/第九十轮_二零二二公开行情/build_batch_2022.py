"""Materialize every candidate, keeping missing replay checkpoints unknown."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import replay_2022 as runner

H = Path(__file__).resolve().parent
B = H / '一秒回放批次'
BENIGN = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    runner.guard(start=True)
    runner.verify_inputs()
    events = pd.read_parquet(H / '候选数据/固定十一币双币过滤潜在触价.parquet')
    fp = runner.fingerprint()
    progress = json.loads((H / '一秒逐笔回放进度.json').read_text(encoding='utf-8'))
    assert progress['fingerprint'] == fp and progress['total_candidates'] == len(events)
    records, archives = {}, []
    for (sym, day), group in events.groupby(['contract', 'day'], sort=True):
        event_rows = group.to_dict('records')
        path = runner.WORK / (runner.key(fp, sym, day, event_rows) + '.json')
        if not path.exists():
            for e in event_rows: records[e['observation_id']] = {'status': 'archive_pending'}
            continue
        cp = json.loads(path.read_text(encoding='utf-8'))
        assert cp['status'] == 'verified' and cp['fingerprint'] == fp
        assert {r['observation_id'] for r in cp['rows']} == set(group.observation_id)
        archives.append({'contract': sym, 'day': day, 'checkpoint_sha256': sha(path), 'archives': cp['archives']})
        for r in cp['rows']:
            assert r['observation_id'] not in records
            records[r['observation_id']] = r
    assert set(records) == set(events.observation_id)
    signals, paths = [], []
    for e in events.to_dict('records'):
        r = records[e['observation_id']]
        pre = r.get('prechecks', {})
        for kind, name in [('original', 'paths'), ('extended', 'extended_paths')]:
            for variant, path in r.get(name, {}).items():
                paths.append({'observation_id': e['observation_id'], 'holding_rule': kind, 'variant': variant, **path})
        signals.append({**e, **{k: v for k, v in r.items() if k not in ('prechecks', 'paths', 'extended_paths')},
                        'precheck_10x': pre.get('10'), 'precheck_20x': pre.get('20')})
    sig = pd.DataFrame(signals)
    paths = pd.DataFrame(paths) if paths else pd.DataFrame(columns=['observation_id', 'holding_rule', 'variant', 'status'])
    assert len(sig) == len(events) and sig.observation_id.is_unique
    assert not paths.duplicated(['observation_id', 'holding_rule', 'variant']).any()
    B.mkdir(exist_ok=True)
    sig.to_parquet(B / '动态池逐笔信号筛查.parquet', index=False)
    paths.to_parquet(B / '动态池延迟市价路径.parquet', index=False)
    unknown = sig.loc[~sig.status.isin(BENIGN), 'observation_id'].tolist()
    result = {'candidate_events': len(sig), 'event_statuses': sig.status.value_counts().to_dict(),
              'unexpected_event_count': len(unknown), 'variant_paths': len(paths),
              'path_statuses': paths.status.value_counts().to_dict(),
              'archive_errors': [{'status': 'unresolved', 'events': unknown}] if unknown else [],
              'archives': archives, 'fingerprint': fp, 'code_sha256': sha(Path(__file__)),
              'unknown_rank_hours': 240, 'note': 'Raw checkpoints only; missing source, risk and liquidation remain unknown.'}
    (B / '动态池逐笔提取质量.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_BATCH', json.dumps({k: v for k, v in result.items() if k != 'archives'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
