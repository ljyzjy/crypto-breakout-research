"""Evaluate the frozen completed-week gate on already-audited unit paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics
from week_gate import gate

getcontext().prec = 40
D = Decimal


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    audit = json.loads((H / '已完成周线独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['audit_code_sha256'] == sha(H / 'audit_week_sources.py')
    assert audit['source_sha256'] == sha(H / '已完成周线来源核验.json')
    tests = json.loads((H / '周线时间与边界测试.json').read_text(encoding='utf-8'))
    assert tests['all_checks_pass'] and tests['gate_code_sha256'] == sha(H / 'week_gate.py')
    assert tests['test_code_sha256'] == sha(H / 'test_week_gate.py')
    prep = json.loads((H / '已完成周线来源核验.json').read_text(encoding='utf-8'))
    weeks = {(x['symbol'], x['week_start']): x for x in prep['weeks']}
    events = {(x['year'], x['observation_id']): x for x in prep['events']}
    detail, starts = [], {}
    for year in ('2023', '2024', '2026'):
        base = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
        oi = P / ('第七十三轮_二零二三扩展核验/2023持仓量冻结结果' if year == '2023' else f'第六十九轮_一秒观察持仓量门/{year}冻结结果')
        bp, op = base / '完整快照哈希.json', oi / '冻结哈希.json'
        assert sha(bp) == frozen['base_snapshots'][year] and sha(op) == frozen['oi_snapshots'][year]
        bm, om = json.loads(bp.read_text(encoding='utf-8')), json.loads(op.read_text(encoding='utf-8'))
        assert bm['all_checks_pass'] and om['all_checks_pass']
        names = ['batch/动态池单位收益与风险.parquet', f'support/{year}一秒观察对照.json']
        oi_names = [f'{year}一秒观察持仓量逐笔.csv', f'{year}持仓量跨期对照.json' if year == '2023' else f'{year}一秒观察持仓量对照.json']
        for name in names:
            assert sha(base / name) == bm['files'][name]
        for name in oi_names:
            assert sha(oi / name) == om['files'][name]
        paths = [x for x in pq.read_table(base / names[0]).to_pylist() if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False]
        with (oi / oi_names[0]).open(encoding='utf-8', newline='') as f:
            oi_rows = {(r['observation_id'], r['variant']): r for r in csv.DictReader(f)}
        assert set(oi_rows) == {(r['observation_id'], r['variant']) for r in paths}
        prev = json.loads((base / names[1]).read_text(encoding='utf-8'))
        oi_prev = json.loads((oi / oi_names[1]).read_text(encoding='utf-8'))
        for lev in (10, 20):
            b = next(x for x in prev['rows'] if x['leverage'] == lev)
            starts[(year, lev)] = {'unknown': b['one_second_observation']['unknown'], 'no_order': b['known_no_order'],
                                   'candidates': b['candidate_events'], 'oi_prev': oi_prev}
        for row in paths:
            obs, variant = row['observation_id'], row['variant']
            e, o = events[(year, obs)], oi_rows[(obs, variant)]
            assert int(e['decision_ts']) == int(row['decision_ts']) == int(o['decision_ts'])
            assert int(row['entry_ts']) >= int(row['decision_ts']) + 1000
            assert int(row['side']) == int(o['side']) == int(e['side'])
            raw_gate = o['gate']
            assert raw_gate in ('True', 'False', '')
            oi_gate = None if raw_gate == '' else raw_gate == 'True'
            g = gate(e, weeks)
            week_gate = g['week_gate']
            both = None if week_gate is None or oi_gate is None else week_gate and oi_gate
            side, entry, raw, funding = int(row['side']), D(str(row['entry_fill'])), D(str(row['exit_raw'])), D(str(row['funding']))
            exit_ = raw * (1 - D(side) * D('.0005'))
            net = D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - funding
            assert abs(net - D(str(row['net_per_unit_notional']))) < D('1e-11')
            assert abs(net - D(o['net'])) < D('1e-11')
            record = {'year': year, 'observation_id': obs, 'variant': variant, 'decision_ts': int(row['decision_ts']),
                      'side': side, **g, 'oi_gate': oi_gate, 'both': both, 'entry_ts': int(row['entry_ts']),
                      'entry_fill': entry, 'exit_raw': raw, 'funding': funding, 'net': net}
            detail.append(record)
    cols = ['year', 'observation_id', 'variant', 'decision_ts', 'side', 'last_week_start', 'BTCUSDT_close', 'BTCUSDT_sma29',
            'ETHUSDT_close', 'ETHUSDT_sma29', 'week_gate', 'oi_gate', 'both', 'entry_ts', 'entry_fill', 'exit_raw', 'funding', 'net']
    path = H / '周线趋势逐笔.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(detail)
    rows = []
    for year in ('2023', '2024', '2026', 'all'):
        period = ('2023', '2024', '2026') if year == 'all' else (year,)
        for lev in (10, 20):
            universe = [x for x in detail if x['year'] in period and x['variant'].endswith(f'_{lev}x')]
            original_unknown = sum(starts[(y, lev)]['unknown'] for y in period)
            original_no_order = sum(starts[(y, lev)]['no_order'] for y in period)
            candidates = sum(starts[(y, lev)]['candidates'] for y in period)
            for cohort in ('base', 'week_gate', 'oi_gate', 'both'):
                chosen = universe if cohort == 'base' else [x for x in universe if x[cohort] is True]
                unknown = original_unknown + (sum(x[cohort] is None for x in universe) if cohort != 'base' else 0)
                no_order = original_no_order + (sum(x[cohort] is False for x in universe) if cohort != 'base' else 0)
                assert len(chosen) + unknown + no_order == candidates
                for slip in (D('.0005'), D('.00075'), D('.001')):
                    selected = []
                    for r in chosen:
                        exit_ = r['exit_raw'] * (1 - D(r['side']) * slip)
                        net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - r['funding']
                        selected.append({**r, 'net': net})
                    rows.append({'year': year, 'leverage': lev, 'cohort': cohort, 'exit_slippage_pct': float(100 * slip),
                                 **metrics(selected, unknown), 'known_no_order': no_order, 'candidate_events': candidates})
            if year != 'all':
                for prior_name, cohort in (('base', 'base'), ('oi_gate', 'oi_gate')):
                    a = next(x for x in rows if x['year'] == year and x['leverage'] == lev and x['cohort'] == cohort and x['exit_slippage_pct'] == .05)
                    b = next(x for x in starts[(year, lev)]['oi_prev']['rows'] if x['leverage'] == lev and x['strategy'] == prior_name and x['exit_slippage_pct'] == .05)
                    for key in ('known_trades', 'net_wins', 'unknown_candidates', 'known_no_order'):
                        assert a[key] == b[key]
                    if a['known_trades']:
                        assert abs(a['mean_net_pct_notional'] - b['mean_net_pct_notional']) < 1e-10
    out = {'rows': rows, 'detail_sha256': sha(path), 'plan_sha256': sha(H / '冻结研究方案.md'),
           'frozen_sha256': sha(H / '冻结时点.json'), 'source_audit_sha256': sha(H / '已完成周线独立核验.json'),
           'gate_test_sha256': sha(H / '周线时间与边界测试.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Retrospective exploration on previously studied periods; unit paths are not account returns or verified fills.'}
    (H / '周线趋势跨期对照.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in rows:
        if r['leverage'] == 20 and r['exit_slippage_pct'] == .05:
            print('WEEK_RESULT', r, flush=True)


if __name__ == '__main__':
    main()
