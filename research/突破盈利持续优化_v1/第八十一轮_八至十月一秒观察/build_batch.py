"""Materialize all 57 candidates; absent checkpoints and errors remain unknown."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import run_replay as runner

H = Path(__file__).resolve().parent
OLD = H.parent / '第六十三轮_2026八至十月延伸'
BENIGN = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    f, _ = runner.verify_inputs()
    data = pd.read_parquet(OLD / '候选数据/固定十一币双币过滤潜在触价.parquet')
    fp = runner.fingerprint()
    records, archives = {}, []
    for (sym, day, needs), group in data.groupby(['contract', 'day', 'needs_next'], sort=True):
        events = group.to_dict('records')
        key = runner.checkpoint_key(fp, sym, day, bool(needs), events)
        path = runner.WORK / (key + '.json')
        if not path.exists():
            for e in events:
                records[e['observation_id']] = {'observation_id': e['observation_id'], 'status': 'archive_pending'}
            continue
        rec = json.loads(path.read_text(encoding='utf-8'))
        assert rec['status'] == 'verified' and rec['fingerprint'] == fp
        assert {x['observation_id'] for x in rec['rows']} == set(group.observation_id)
        archives.append({'contract': sym, 'day': day, 'checkpoint_sha256': sha(path), 'archives': rec['archives']})
        for x in rec['rows']:
            assert x['observation_id'] not in records
            records[x['observation_id']] = x
    assert set(records) == set(data.observation_id)
    signals, paths = [], []
    for event in data.to_dict('records'):
        r = records[event['observation_id']]
        pre = r.get('prechecks', {})
        for variant, path in r.get('paths', {}).items():
            paths.append({'observation_id': event['observation_id'], 'variant': variant, **path})
        signals.append({**event, **{k: v for k, v in r.items() if k not in ('prechecks', 'paths')},
                        'precheck_10x': pre.get('10'), 'precheck_20x': pre.get('20')})
    signals = pd.DataFrame(signals)
    paths = pd.DataFrame(paths) if paths else pd.DataFrame(columns=['observation_id', 'variant', 'status'])
    assert not paths.duplicated(['observation_id', 'variant']).any() and len(signals) == 57
    target = H / '一秒回放批次'
    target.mkdir(exist_ok=True)
    signals.to_parquet(target / '动态池逐笔信号筛查.parquet', index=False)
    paths.to_parquet(target / '动态池延迟市价路径.parquet', index=False)
    unknown = signals.loc[~signals.status.isin(BENIGN), 'observation_id'].tolist()
    quality = {'candidate_events': len(signals), 'event_statuses': signals.status.value_counts().to_dict(),
               'unexpected_event_count': len(unknown), 'variant_paths': len(paths),
               'unverified_path_count': int((~paths.status.eq('verified')).sum()),
               'archive_errors': [{'status': 'unresolved', 'events': unknown}] if unknown else [],
               'archives': archives, 'fingerprint': fp, 'code_sha256': sha(Path(__file__)),
               'note': 'Pending, source mismatch, risk gaps and actual liquidation proxy remain unknown.'}
    (target / '动态池逐笔提取质量.json').write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding='utf-8')
    execution = {'plan_sha256': sha(H / '冻结研究方案.md'), 'frozen_sha256': sha(H / '冻结时点.json'),
                 'observation_ms': 1000, 'entry_delay_ms': 1000, 'exit_delay_ms': 5000,
                 'fee_per_side': .0005, 'adverse_slippage_per_side': .0005, 'target_r': 2}
    (target / '逐笔执行冻结方案.json').write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_BATCH', json.dumps({k: v for k, v in quality.items() if k != 'archives'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
