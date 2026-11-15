"""Independently recompute all paired 2R/3R cost and sample summaries."""
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
    result_path = H / f'{year}三倍止盈配对对照.json'
    out = json.loads(result_path.read_text(encoding='utf-8'))
    assert out['code_sha256'] == sha(H / 'describe_3r.py') and out['plan_sha256'] == sha(H / '冻结研究方案.md')
    risk_path, detail_path = H / f'{year}三倍止盈风险账本.json', H / f'{year}三倍止盈配对逐笔.csv'
    assert out['risk_ledger_sha256'] == sha(risk_path) and out['detail_sha256'] == sha(detail_path) and len(out['rows']) == 24
    risk = json.loads(risk_path.read_text(encoding='utf-8'))
    la = json.loads((H / f'{year}三倍止盈账本独立核验.json').read_text(encoding='utf-8'))
    ta = json.loads((H / f'{year}三倍止盈逐笔独立核验.json').read_text(encoding='utf-8'))
    assert la['all_checks_pass'] and la['ledger_sha256'] == sha(risk_path) and ta['all_checks_pass']
    base = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
    oi = P / ('第七十三轮_二零二三扩展核验/2023持仓量冻结结果' if year == '2023' else f'第六十九轮_一秒观察持仓量门/{year}冻结结果')
    assert sha(base / '完整快照哈希.json') == risk['source_snapshot_sha256']
    bm, om = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8')), json.loads((oi / '冻结哈希.json').read_text(encoding='utf-8'))
    file = base / 'batch/动态池单位收益与风险.parquet'
    assert sha(file) == bm['files']['batch/动态池单位收益与风险.parquet']
    old_rows = [r for r in pq.read_table(file).to_pylist() if r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False]
    old = {(r['observation_id'], r['variant']): r for r in old_rows}
    new = {(r['observation_id'], r['variant'].replace('_3r_', '_2r_')): r for r in risk['records']
           if r.get('status') == r.get('risk_status') == 'verified' and r.get('liq_proxy') is False}
    gate_path = oi / f'{year}一秒观察持仓量逐笔.csv'
    prior_path = oi / ('2023持仓量跨期对照.json' if year == '2023' else f'{year}一秒观察持仓量对照.json')
    assert sha(gate_path) == om['files'][gate_path.name] and sha(prior_path) == om['files'][prior_path.name]
    with gate_path.open(encoding='utf-8', newline='') as f:
        gate = {(r['observation_id'], r['variant']): r['gate'] for r in csv.DictReader(f)}
    prior = json.loads(prior_path.read_text(encoding='utf-8'))['rows']
    with detail_path.open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    assert len({(r['leverage'], r['cohort'], r['observation_id']) for r in detail}) == len(detail)
    for r in detail:
        lev, obs = int(r['leverage']), r['observation_id']
        key = (obs, f'one_observation_2r_{lev}x')
        a, b = old[key], new[key]
        if r['cohort'] == 'oi_gate':
            assert gate[key] == 'True'
        for field, value in [('entry_ts', a['entry_ts']), ('entry_fill', a['entry_fill']), ('old_exit_ts', a['exit_ts']),
                             ('old_exit_raw', a['exit_raw']), ('old_funding', a['funding']), ('old_net', a['net_per_unit_notional']),
                             ('new_exit_ts', b['exit_ts']), ('new_exit_raw', b['exit_raw']), ('new_funding', b['funding']),
                             ('new_net', b['net_per_unit_notional'])]:
            assert near(r[field], value)
        assert r['old_reason'] == a['reason'] and r['new_reason'] == b['reason'] and r['source_mode'] == b['source_mode']
    checked = 0
    for r in out['rows']:
        lev, cohort, target, slip = r['leverage'], r['cohort'], r['exit_target'], r['exit_slippage_pct'] / 100
        variant = f'one_observation_2r_{lev}x'
        universe = [key for key in old if key[1] == variant and (cohort == 'base' or gate[key] == 'True')]
        paired = [key for key in universe if key in new]
        source = next(x for x in prior if x['leverage'] == lev and x['strategy'] == cohort and x['exit_slippage_pct'] == .05)
        assert len(universe) == r['eligible_2r_trades'] == source['known_trades']
        assert r['additional_unpaired_unknown'] == len(universe) - len(paired)
        assert r['unknown_candidates'] == source['unknown_candidates'] + len(universe) - len(paired)
        assert r['known_no_order'] == source['known_no_order']
        vals, days = [], set()
        for key in paired:
            x = old[key] if target == '2r' else new[key]
            entry, side = float(x['entry_fill']), int(x['side'])
            exit_ = float(x['exit_raw']) * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(x['funding']))
            days.add(datetime.fromtimestamp(int(x['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(vals), sum(v > 0 for v in vals)
        pos, neg = math.fsum(v for v in vals if v > 0), -math.fsum(v for v in vals if v < 0)
        assert r['known_trades'] == n and r['net_wins'] == wins and r['active_utc_days'] == len(days)
        assert near(r['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(r['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(r['profit_factor'], pos / neg if neg else None)
        assert near(r['worst_net_pct_notional'], 100 * min(vals) if n else None)
        checked += 1
    audit = {'all_checks_pass': True, 'year': year, 'groups_checked': checked, 'detail_rows_checked': len(detail),
             'result_sha256': sha(result_path), 'audit_code_sha256': sha(Path(__file__)),
             'note': 'Matched historical units, no live fills or shared-account equity.'}
    (H / f'{year}三倍止盈汇总独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('THREE_R_SUMMARY_AUDIT', year, checked, len(detail), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
