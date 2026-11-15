"""Identify every originally quarter-time path and trace its immutable tape source."""
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    f = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert f['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, path in f['source_paths'].items():
        assert sha(Path(path)) == f['sources_sha256'][name]
    test = json.loads((H / '延长持有合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(H / 'extend_exit.py')
    assert test['test_code_sha256'] == sha(H / 'test_extend_exit.py')
    frozen = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    events, counts = [], {}
    fields = ['observation_id', 'contract', 'day', 'trigger_minute', 'quarter_start', 'quarter_end', 'upper', 'lower',
              'atr', 'long_known_eligible', 'short_known_eligible', 'long_spec', 'short_spec']
    pathfields = ['variant', 'status', 'side', 'decision_ts', 'entry_ts', 'entry_raw', 'entry_fill', 'entry_signal_reference_ts',
                  'exit_signal_ts', 'exit_ts', 'exit_raw', 'exit_fill', 'reason', 'initial_stop', 'funding',
                  'funding_events_json', 'risk_status', 'liq_proxy', 'net_per_unit_notional', 'quarter_end']
    for period in PERIODS:
        if period == '2026_aug_oct':
            root, manifest = R81 / '冻结结果', R81 / '冻结结果/冻结哈希.json'
            assert sha(manifest) == f['sources_sha256']['r81_snapshot']
        else:
            root = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            manifest = root / '完整快照哈希.json'
            assert sha(manifest) == frozen['base_snapshots'][period]
        m = json.loads(manifest.read_text(encoding='utf-8'))
        sp, lp = 'batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet'
        assert sha(root / sp) == m['files'][sp] and sha(root / lp) == m['files'][lp]
        signals = {x['observation_id']: x for x in pq.read_table(root / sp).to_pylist()}
        selected = [x for x in pq.read_table(root / lp).to_pylist()
                    if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False and x['reason'] == 'quarter_time']
        wanted = {x['observation_id'] for x in selected}
        checkpoint = {}
        for cp in (root / 'checkpoints').glob('*.json'):
            key = 'checkpoints/' + cp.name
            assert sha(cp) == m['files'][key]
            z = json.loads(cp.read_text(encoding='utf-8'))
            for row in z['rows']:
                if row['observation_id'] in wanted:
                    assert row['observation_id'] not in checkpoint
                    checkpoint[row['observation_id']] = {'path': str(cp), 'sha256': sha(cp), 'archives': z['archives'], 'row': row}
        assert set(checkpoint) == wanted
        for obs in sorted(wanted):
            s = signals[obs]
            rows = [x for x in selected if x['observation_id'] == obs]
            assert len(rows) == 2 and {r['variant'] for r in rows} == {'one_observation_2r_10x', 'one_observation_2r_20x'}
            assert s['status'] == checkpoint[obs]['row']['status'] == 'qualified'
            event = {k: s[k] for k in fields}
            paths = [{k: r[k] for k in pathfields} for r in rows]
            events.append({'period': period, 'event': event, 'paths': paths, 'checkpoint': checkpoint[obs]})
        counts[period] = len(wanted)
    assert counts == {'2023': 15, '2024': 10, '2026': 5, '2026_aug_oct': 4}
    out = {'events': events, 'counts': counts, 'original_paired_paths': sum(len(e['paths']) for e in events),
           'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Original quarter-time paths only; no extended outcomes calculated.'}
    (H / '原柱末退出回放输入.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT88_INPUTS', counts, 'paths', out['original_paired_paths'], flush=True)


if __name__ == '__main__':
    main()
