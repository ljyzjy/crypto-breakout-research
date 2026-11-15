"""Independently rederive the cost-scale gate and all 120 summary groups."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
R82 = P / '第八十二轮_八至十月持仓量过滤'
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')
D = Decimal


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    result_path = H / '首秒距离跨期对照.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'evaluate_extension.py') and result['frozen_sha256'] == sha(H / '冻结时点.json')
    assert result['test_sha256'] == sha(H / '追价距离合成核验.json') and result['detail_sha256'] == sha(H / '首秒距离逐笔.csv')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    for name, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][name]
    with (H / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    assert len(detail) == 226 and len({(x['period'], x['observation_id'], x['variant']) for x in detail}) == 226
    old = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    paths, signals, oi_gates, base = {}, {}, {}, {}
    for period in PERIODS:
        if period == '2026_aug_oct':
            b, o = R81 / '冻结结果', R82 / '冻结结果'
            bm, om = b / '冻结哈希.json', o / '冻结哈希.json'
            assert sha(bm) == frozen['sources_sha256']['r81_freeze'] and sha(om) == frozen['sources_sha256']['r82_freeze']
            oi_name, sum_name = '持仓量过滤逐笔.csv', '持仓量过滤对照.json'
        else:
            b = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            o = P / ('第七十三轮_二零二三扩展核验/2023持仓量冻结结果' if period == '2023' else f'第六十九轮_一秒观察持仓量门/{period}冻结结果')
            bm, om = b / '完整快照哈希.json', o / '冻结哈希.json'
            assert sha(bm) == old['base_snapshots'][period] and sha(om) == old['oi_snapshots'][period]
            oi_name = f'{period}一秒观察持仓量逐笔.csv'
            sum_name = f'{period}持仓量跨期对照.json' if period == '2023' else f'{period}一秒观察持仓量对照.json'
        bmeta, ometa = json.loads(bm.read_text(encoding='utf-8')), json.loads(om.read_text(encoding='utf-8'))
        sn, pn = 'batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet'
        assert sha(b / sn) == bmeta['files'][sn] and sha(b / pn) == bmeta['files'][pn]
        assert sha(o / oi_name) == ometa['files'][oi_name] and sha(o / sum_name) == ometa['files'][sum_name]
        for s in pq.read_table(b / sn).to_pylist(): signals[(period, s['observation_id'])] = s
        for r in pq.read_table(b / pn).to_pylist():
            if r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False:
                paths[(period, r['observation_id'], r['variant'])] = r
        with (o / oi_name).open(encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                variant = f"one_observation_2r_{r['leverage']}x" if period == '2026_aug_oct' else r['variant']
                oi_gates[(period, r['observation_id'], variant)] = r['oi_gate'] if period == '2026_aug_oct' else r['gate']
        prior = json.loads((o / sum_name).read_text(encoding='utf-8'))
        for lev in (10, 20):
            base[(period, lev)] = next(x for x in prior['rows'] if x['leverage'] == lev and x['exit_slippage_pct'] == .05 and
                                       (x['cohort'] == 'base' if period == '2026_aug_oct' else x['strategy'] == 'base'))
    assert set(paths) == set(oi_gates) == {(r['period'], r['observation_id'], r['variant']) for r in detail}
    for row in detail:
        key = row['period'], row['observation_id'], row['variant']
        s, p = signals[key[:2]], paths[key]
        assert int(row['decision_ts']) == s['decision_ts'] and int(row['reference_ts']) == s['entry_exec_ts'] >= s['decision_ts'] + 1000
        assert int(row['side']) == s['side'] == p['side']
        ref, level, side = D(str(s['raw_entry_1s'])), D(str(s['level'])), D(s['side'])
        assert D(row['reference']) == ref and D(row['level']) == level
        # Cross-multiplication avoids using the implementation's division for the threshold.
        numerator = side * (ref - level)
        extension = numerator > 0 and numerator * D(2000) <= level
        assert row['extension_gate'] == str(extension) and near(row['distance'], numerator / level)
        oi = oi_gates[key]
        assert row['oi_gate'] == oi
        both = '' if oi == '' else str(extension and oi == 'True')
        assert row['both'] == both
        for name in ('entry_ts', 'entry_fill', 'exit_raw', 'funding'):
            assert near(row[name], p[name])
        assert near(row['net'], p['net_per_unit_notional'])
    assert len(result['rows']) == 120
    for out in result['rows']:
        included = PERIODS if out['period'] == 'all' else (out['period'],)
        lev, cohort, slip = out['leverage'], out['cohort'], out['exit_slippage_pct'] / 100
        universe = [r for r in detail if r['period'] in included and r['variant'].endswith(f'_{lev}x')]
        selected = universe if cohort == 'base' else [r for r in universe if r[cohort] == 'True']
        unknown = sum(base[(p, lev)]['unknown_candidates'] for p in included)
        no_order = sum(base[(p, lev)]['known_no_order'] for p in included)
        if cohort != 'base':
            unknown += sum(r[cohort] == '' for r in universe)
            no_order += sum(r[cohort] == 'False' for r in universe)
        expected_total = sum(base[(p, lev)]['known_trades'] + base[(p, lev)]['unknown_candidates'] + base[(p, lev)]['known_no_order'] for p in included)
        assert out['unknown_candidates'] == unknown and out['known_no_order'] == no_order
        assert len(selected) + unknown + no_order == expected_total == out['candidate_events']
        vals, days = [], set()
        for r in selected:
            side, entry, raw = int(r['side']), float(r['entry_fill']), float(r['exit_raw'])
            exit_ = raw * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r['funding']))
            days.add(datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(vals), sum(x > 0 for x in vals)
        pos, neg = math.fsum(x for x in vals if x > 0), -math.fsum(x for x in vals if x < 0)
        assert out['known_trades'] == n and out['net_wins'] == wins and out['active_utc_days'] == len(days)
        assert near(out['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(out['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(out['profit_factor'], pos / neg if neg else None)
    output = {'all_checks_pass': True, 'detail_rows_checked': len(detail), 'groups_checked': len(result['rows']),
              'result_sha256': sha(result_path), 'detail_sha256': sha(H / '首秒距离逐笔.csv'),
              'code_sha256': sha(Path(__file__)), 'note': 'Historical arithmetic and time check; not blind or account outcomes.'}
    (H / '首秒距离独立核验.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT86_AUDIT', json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
