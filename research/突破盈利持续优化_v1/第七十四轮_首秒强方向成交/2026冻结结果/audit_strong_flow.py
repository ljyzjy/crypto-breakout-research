"""Independently check one-second imbalance gate and paired costs."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main(year):
    result_path = H / f'{year}强方向对照.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert result['plan_sha256'] == sha(H / '冻结研究方案.md') and result['code_sha256'] == sha(H / 'evaluate_strong_flow.py')
    detail_path = H / f'{year}强方向逐笔.csv'
    assert result['detail_sha256'] == sha(detail_path) and len(result['rows']) == 24
    base = P / (f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结' if year != '2023' else '第七十三轮_二零二三扩展核验/2023基础冻结结果')
    manifest_path = base / '完整快照哈希.json'
    assert result['source_base_sha256'] == sha(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    signal_path = base / 'batch/动态池逐笔信号筛查.parquet'
    assert sha(signal_path) == manifest['files']['batch/动态池逐笔信号筛查.parquet']
    signals = {x['observation_id']: x for x in pq.read_table(signal_path).to_pylist()}
    oi = P / (f'第六十九轮_一秒观察持仓量门/{year}冻结结果' if year != '2023' else '第七十三轮_二零二三扩展核验/2023持仓量冻结结果')
    oi_manifest = oi / '冻结哈希.json'
    assert result['source_oi_sha256'] == sha(oi_manifest)
    oi_meta = json.loads(oi_manifest.read_text(encoding='utf-8'))
    oi_csv = oi / f'{year}一秒观察持仓量逐笔.csv'
    assert sha(oi_csv) == oi_meta['files'][oi_csv.name]
    with oi_csv.open(encoding='utf-8', newline='') as f:
        gate = {(r['observation_id'], r['variant']): r['gate'] for r in csv.DictReader(f)}
    with detail_path.open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    assert len({(x['observation_id'], x['variant']) for x in detail}) == len(detail)
    for r in detail:
        s = signals[r['observation_id']]
        assert int(r['decision_ts']) == int(s['decision_ts']) and int(r['one_count']) == int(s['one_count']) >= 3
        buy, sell, side = float(s['buy_notional']), float(s['sell_notional']), int(r['side'])
        imbalance = side * (buy - sell) / (buy + sell)
        assert near(imbalance, r['imbalance']) and near(imbalance, s['one_imbalance'])
        strong = imbalance >= .5
        assert r['strong_flow'] == str(strong)
        prior = gate[(r['observation_id'], r['variant'])]
        assert r['oi_gate'] == prior
        both = '' if prior == '' else str(strong and prior == 'True')
        assert r['both'] == both
    checked = 0
    candidates = {'2023': 146, '2024': 119, '2026': 39}[year]
    for out in result['rows']:
        lev, cohort, slip = out['leverage'], out['cohort'], out['exit_slippage_pct'] / 100
        universe = [x for x in detail if x['variant'].endswith(f'_{lev}x')]
        selected = universe if cohort == 'base' else [x for x in universe if x[cohort] == 'True']
        baseline = next(x for x in result['rows'] if x['leverage'] == lev and x['cohort'] == 'base' and x['exit_slippage_pct'] == .05)
        unknown = baseline['unknown_candidates'] + (sum(x[cohort] == '' for x in universe) if cohort != 'base' else 0)
        no_order = baseline['known_no_order'] + (sum(x[cohort] == 'False' for x in universe) if cohort != 'base' else 0)
        assert out['unknown_candidates'] == unknown and out['known_no_order'] == no_order
        assert len(selected) + unknown + no_order == candidates
        values, days = [], set()
        for r in selected:
            entry, side, raw = float(r['entry_fill']), int(r['side']), float(r['exit_raw'])
            exit_ = raw * (1 - side * slip)
            values.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r['funding']))
            days.add(datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(values), sum(v > 0 for v in values)
        pos, neg = math.fsum(v for v in values if v > 0), -math.fsum(v for v in values if v < 0)
        assert out['known_trades'] == n and out['net_wins'] == wins and out['active_utc_days'] == len(days)
        assert near(out['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(out['mean_net_pct_notional'], 100 * math.fsum(values) / n if n else None)
        assert near(out['profit_factor'], pos / neg if neg else None)
        checked += 1
    audit = {'all_checks_pass': True, 'year': year, 'groups_checked': checked, 'detail_rows_checked': len(detail),
             'result_sha256': sha(result_path), 'audit_code_sha256': sha(Path(__file__)),
             'note': 'Post-hoc historical comparison; exact live fills and account equity are not established.'}
    (H / f'{year}强方向独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('STRONG_FLOW_AUDIT', year, checked, len(detail), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
