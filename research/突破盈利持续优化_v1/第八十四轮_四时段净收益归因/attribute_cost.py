import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
getcontext().prec = 40
D = Decimal


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    combined_audit = json.loads((R81 / '四时段合并独立核验.json').read_text(encoding='utf-8'))
    assert combined_audit['all_checks_pass'] and combined_audit['result_sha256'] == sha(R81 / '四时段等名义合并.json')
    with (R81 / '四时段已核验逐笔.csv').open(encoding='utf-8', newline='') as f:
        expected = {(x['period'], x['observation_id']): D(x['net']) for x in csv.DictReader(f) if x['variant'].endswith('_20x')}
    assert len(expected) == 113
    frozen = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    details = []
    for period in ('2023', '2024', '2026', '2026_aug_oct'):
        if period == '2026_aug_oct':
            root = R81 / '冻结结果'
            manifest = json.loads((root / '冻结哈希.json').read_text(encoding='utf-8'))
            assert manifest['all_checks_pass']
            path = root / 'batch/动态池单位收益与风险.parquet'
            assert sha(path) == manifest['files']['batch/动态池单位收益与风险.parquet']
        else:
            root = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            mp = root / '完整快照哈希.json'
            assert sha(mp) == frozen['base_snapshots'][period]
            manifest = json.loads(mp.read_text(encoding='utf-8'))
            path = root / 'batch/动态池单位收益与风险.parquet'
            assert sha(path) == manifest['files']['batch/动态池单位收益与风险.parquet']
        for row in pq.read_table(path).to_pylist():
            if not (row['variant'].endswith('_20x') and row['status'] == row['risk_status'] == 'verified' and row['liq_proxy'] is False):
                continue
            key = period, row['observation_id']
            assert key in expected
            entry_raw, fill = D(str(row['entry_raw'])), D(str(row['entry_fill']))
            exit_raw, exit_fill = D(str(row['exit_raw'])), D(str(row['exit_fill']))
            side, funding = D(int(row['side'])), D(str(row['funding']))
            raw_move = side * (exit_raw - entry_raw) / fill
            entry_slip = side * (entry_raw - fill) / fill
            exit_slip = side * (exit_fill - exit_raw) / fill
            fees = -D('.0005') - D('.0005') * exit_fill / fill
            net = raw_move + entry_slip + exit_slip + fees - funding
            assert abs(net - D(str(row['net_per_unit_notional']))) < D('1e-11')
            assert abs(net - expected[key]) < D('1e-11')
            details.append({'period': period, 'observation_id': row['observation_id'], 'entry_ts': int(row['entry_ts']),
                            'exit_ts': int(row['exit_ts']), 'exit_reason': row['reason'], 'raw_move': raw_move,
                            'entry_slip': entry_slip, 'exit_slip': exit_slip, 'fees': fees, 'funding': -funding, 'net': net})
    assert len(details) == len(expected) == 113
    fields = ['raw_move', 'entry_slip', 'exit_slip', 'fees', 'funding', 'net']
    groups = []
    for period in ('2023', '2024', '2026', '2026_aug_oct', 'all'):
        selected = details if period == 'all' else [r for r in details if r['period'] == period]
        reasons = {}
        for why in sorted({x['exit_reason'] for x in selected}):
            subset = [x for x in selected if x['exit_reason'] == why]
            reasons[why] = {'trades': len(subset), 'net_wins': sum(x['net'] > 0 for x in subset),
                            'mean_net_pct_notional': float(100 * sum((x['net'] for x in subset), D(0)) / len(subset))}
        groups.append({'period': period, 'trades': len(selected), 'raw_reference_positive': sum(x['raw_move'] > 0 for x in selected),
                       'net_wins': sum(x['net'] > 0 for x in selected),
                       'raw_positive_net_nonpositive': sum(x['raw_move'] > 0 and x['net'] <= 0 for x in selected),
                       'mean_contribution_pct_notional': {k: float(100 * sum((x[k] for x in selected), D(0)) / len(selected)) for k in fields},
                       'exit_reasons': reasons})
    path = H / '四时段成本归因逐笔.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['period', 'observation_id', 'entry_ts', 'exit_ts', 'exit_reason', *fields]); w.writeheader(); w.writerows(details)
    out = {'groups': groups, 'detail_sha256': sha(path), 'combined_source_sha256': sha(R81 / '四时段等名义合并.json'),
           'combined_audit_sha256': sha(R81 / '四时段合并独立核验.json'), 'plan_sha256': sha(H / '研究口径.md'),
           'code_sha256': sha(Path(__file__)), 'note': 'Post-hoc equal-notional cost decomposition, not executable future filter.'}
    (H / '四时段成本归因.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for group in groups:
        print('EXT84_COST', json.dumps(group, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
