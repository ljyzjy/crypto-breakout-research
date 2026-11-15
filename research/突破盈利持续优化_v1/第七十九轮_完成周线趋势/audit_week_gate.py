"""Independently recompute all week gates, accounting and summary groups."""
import csv
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
W, MON = 604800000, 345600000
getcontext().prec = 50
D = Decimal


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '周线趋势跨期对照.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['plan_sha256'] == sha(H / '冻结研究方案.md')
    assert result['frozen_sha256'] == sha(H / '冻结时点.json')
    assert result['source_audit_sha256'] == sha(H / '已完成周线独立核验.json')
    assert result['gate_test_sha256'] == sha(H / '周线时间与边界测试.json')
    assert result['code_sha256'] == sha(H / 'evaluate_week_gate.py')
    detail_path = H / '周线趋势逐笔.csv'
    assert result['detail_sha256'] == sha(detail_path)
    with detail_path.open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    assert len(detail) == 196 and len({(r['year'], r['observation_id'], r['variant']) for r in detail}) == 196
    prep = json.loads((H / '已完成周线来源核验.json').read_text(encoding='utf-8'))
    assert json.loads((H / '已完成周线独立核验.json').read_text(encoding='utf-8'))['source_sha256'] == sha(H / '已完成周线来源核验.json')
    week = {(r['symbol'], int(r['week_start'])): r for r in prep['weeks']}
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    path_lookup, oi_lookup, baseline = {}, {}, {}
    for year in ('2023', '2024', '2026'):
        b = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
        o = P / ('第七十三轮_二零二三扩展核验/2023持仓量冻结结果' if year == '2023' else f'第六十九轮_一秒观察持仓量门/{year}冻结结果')
        bm, om = b / '完整快照哈希.json', o / '冻结哈希.json'
        assert sha(bm) == frozen['base_snapshots'][year] and sha(om) == frozen['oi_snapshots'][year]
        bmeta, ometa = json.loads(bm.read_text(encoding='utf-8')), json.loads(om.read_text(encoding='utf-8'))
        pn, bn, on = 'batch/动态池单位收益与风险.parquet', f'support/{year}一秒观察对照.json', f'{year}一秒观察持仓量逐笔.csv'
        assert sha(b / pn) == bmeta['files'][pn] and sha(b / bn) == bmeta['files'][bn] and sha(o / on) == ometa['files'][on]
        for r in pq.read_table(b / pn).to_pylist():
            if r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False:
                path_lookup[(year, r['observation_id'], r['variant'])] = r
        with (o / on).open(encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                oi_lookup[(year, r['observation_id'], r['variant'])] = r['gate']
        base = json.loads((b / bn).read_text(encoding='utf-8'))
        for r in base['rows']:
            baseline[(year, r['leverage'])] = r
    assert set(path_lookup) == set(oi_lookup) == {(r['year'], r['observation_id'], r['variant']) for r in detail}
    for row in detail:
        key = row['year'], row['observation_id'], row['variant']
        original = path_lookup[key]
        decision, side = int(row['decision_ts']), int(row['side'])
        assert decision == original['decision_ts'] and side == original['side']
        assert int(row['entry_ts']) == original['entry_ts'] and int(row['entry_ts']) >= decision + 1000
        for f in ('entry_fill', 'exit_raw', 'funding'):
            assert D(row[f]) == D(str(original[f]))
        last = ((decision - MON) // W) * W + MON - W
        assert last == int(row['last_week_start']) and last + W <= decision < last + 2 * W
        choices = []
        for symbol in ('BTCUSDT', 'ETHUSDT'):
            closes = []
            for i in range(29):
                start = last - i * W
                x = week[(symbol, start)]
                assert x['status'] == 'verified' and x['week_end_exclusive'] == start + W <= decision
                closes.append(D(str(x['official_ohlc']['close'])))
            assert D(row[symbol + '_close']) == closes[0]
            assert near(row[symbol + '_sma29'], sum(closes) / D(29))
            choices.append(D(side) * (D(29) * closes[0] - sum(closes)) > 0)
        flag = all(choices)
        assert row['week_gate'] == str(flag) and row['oi_gate'] == oi_lookup[key]
        both = '' if row['oi_gate'] == '' else str(flag and row['oi_gate'] == 'True')
        assert row['both'] == both
        entry, raw, funding = D(row['entry_fill']), D(row['exit_raw']), D(row['funding'])
        exit_ = raw * (1 - D(side) * D('.0005'))
        net = D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - funding
        assert abs(net - D(row['net'])) < D('1e-35')
    assert len(result['rows']) == 96
    for out in result['rows']:
        year, lev, cohort = out['year'], out['leverage'], out['cohort']
        period = ('2023', '2024', '2026') if year == 'all' else (year,)
        universe = [x for x in detail if x['year'] in period and x['variant'].endswith(f'_{lev}x')]
        chosen = universe if cohort == 'base' else [x for x in universe if x[cohort] == 'True']
        unknown = sum(baseline[(y, lev)]['one_second_observation']['unknown'] for y in period)
        no_order = sum(baseline[(y, lev)]['known_no_order'] for y in period)
        if cohort != 'base':
            unknown += sum(x[cohort] == '' for x in universe)
            no_order += sum(x[cohort] == 'False' for x in universe)
        candidates = sum(baseline[(y, lev)]['candidate_events'] for y in period)
        assert len(chosen) + unknown + no_order == candidates
        assert out['unknown_candidates'] == unknown and out['known_no_order'] == no_order and out['candidate_events'] == candidates
        nums, days = [], set()
        slip = out['exit_slippage_pct'] / 100
        for x in chosen:
            side, entry, raw = int(x['side']), float(x['entry_fill']), float(x['exit_raw'])
            exit_ = raw * (1 - side * slip)
            nums.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(x['funding']))
            days.add(datetime.fromtimestamp(int(x['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(nums), sum(x > 0 for x in nums)
        positive, negative = math.fsum(x for x in nums if x > 0), -math.fsum(x for x in nums if x < 0)
        assert out['known_trades'] == n and out['net_wins'] == wins and out['active_utc_days'] == len(days)
        assert near(out['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(out['mean_net_pct_notional'], 100 * math.fsum(nums) / n if n else None)
        assert near(out['profit_factor'], positive / negative if negative else None)
        assert near(out['worst_net_pct_notional'], 100 * min(nums) if nums else None)
    audit = {'all_checks_pass': True, 'detail_rows_checked': len(detail), 'groups_checked': len(result['rows']),
             'result_sha256': sha(path), 'detail_sha256': sha(detail_path), 'audit_code_sha256': sha(Path(__file__)),
             'note': 'Independent arithmetic audit, not independent prospective strategy validation.'}
    (H / '周线趋势独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WEEK_GATE_AUDIT', audit, flush=True)


if __name__ == '__main__':
    main()
