import csv
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '四时段成本归因.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'attribute_cost.py') and result['plan_sha256'] == sha(H / '研究口径.md')
    assert result['combined_source_sha256'] == sha(R81 / '四时段等名义合并.json')
    assert result['combined_audit_sha256'] == sha(R81 / '四时段合并独立核验.json')
    assert result['detail_sha256'] == sha(H / '四时段成本归因逐笔.csv')
    with (H / '四时段成本归因逐笔.csv').open(encoding='utf-8', newline='') as f:
        detail = {(x['period'], x['observation_id']): x for x in csv.DictReader(f)}
    assert len(detail) == 113
    sources = {}
    for period in ('2023', '2024', '2026', '2026_aug_oct'):
        if period == '2026_aug_oct':
            root = R81 / '冻结结果'
            info = json.loads((root / '冻结哈希.json').read_text(encoding='utf-8'))
        else:
            root = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            info = json.loads((root / '完整快照哈希.json').read_text(encoding='utf-8'))
        source = root / 'batch/动态池单位收益与风险.parquet'
        assert sha(source) == info['files']['batch/动态池单位收益与风险.parquet']
        for r in pq.read_table(source).to_pylist():
            if r['variant'].endswith('_20x') and r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False:
                sources[(period, r['observation_id'])] = r
    assert set(detail) == set(sources)
    cols = ['raw_move', 'entry_slip', 'exit_slip', 'fees', 'funding', 'net']
    for key, row in detail.items():
        r = sources[key]
        s, entryraw, entry, exitraw, exit_ = int(r['side']), float(r['entry_raw']), float(r['entry_fill']), float(r['exit_raw']), float(r['exit_fill'])
        parts = {'raw_move': s * (exitraw - entryraw) / entry,
                 'entry_slip': s * (entryraw - entry) / entry,
                 'exit_slip': s * (exit_ - exitraw) / entry,
                 'fees': -.0005 - .0005 * exit_ / entry,
                 'funding': -float(r['funding'])}
        parts['net'] = math.fsum(parts.values())
        assert row['exit_reason'] == r['reason'] and int(row['entry_ts']) == r['entry_ts'] and int(row['exit_ts']) == r['exit_ts']
        assert all(near(row[k], parts[k]) for k in cols) and near(parts['net'], r['net_per_unit_notional'])
    for group in result['groups']:
        selected = [r for r in detail.values() if group['period'] == 'all' or r['period'] == group['period']]
        assert group['trades'] == len(selected)
        assert group['raw_reference_positive'] == sum(float(r['raw_move']) > 0 for r in selected)
        assert group['net_wins'] == sum(float(r['net']) > 0 for r in selected)
        assert group['raw_positive_net_nonpositive'] == sum(float(r['raw_move']) > 0 and float(r['net']) <= 0 for r in selected)
        for col in cols:
            assert near(group['mean_contribution_pct_notional'][col], 100 * math.fsum(float(r[col]) for r in selected) / len(selected))
        reasons = {r['exit_reason'] for r in selected}
        assert reasons == set(group['exit_reasons'])
        for why in reasons:
            subset = [r for r in selected if r['exit_reason'] == why]
            out = group['exit_reasons'][why]
            assert out['trades'] == len(subset) and out['net_wins'] == sum(float(r['net']) > 0 for r in subset)
            assert near(out['mean_net_pct_notional'], 100 * math.fsum(float(r['net']) for r in subset) / len(subset))
    out = {'all_checks_pass': True, 'paths_checked': len(detail), 'groups_checked': len(result['groups']),
           'result_sha256': sha(path), 'detail_sha256': sha(H / '四时段成本归因逐笔.csv'),
           'code_sha256': sha(Path(__file__)), 'note': 'Arithmetic attribution of known unit outcomes, not an ex ante filter.'}
    (H / '成本归因独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT84_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
