"""Recalculate matched 1R/2R summaries from frozen entries and audited ledger."""
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
    result_file = H / f'{year}一倍止盈配对对照.json'
    result = json.loads(result_file.read_text(encoding='utf-8'))
    assert result['inputs']['code_sha256'] == sha(H / 'describe_1r.py') and len(result['rows']) == 24
    risk_file = H / f'{year}一倍止盈本地风险账本.json'
    risk = json.loads(risk_file.read_text(encoding='utf-8'))
    assert result['inputs']['risk_ledger_sha256'] == sha(risk_file)
    ledger_audit = json.loads((H / f'{year}一倍止盈账本独立核验.json').read_text(encoding='utf-8'))
    tape_audit = json.loads((H / f'{year}一倍止盈逐笔独立核验.json').read_text(encoding='utf-8'))
    assert ledger_audit['all_checks_pass'] and ledger_audit['ledger_sha256'] == sha(risk_file) and tape_audit['all_checks_pass']
    snap = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结'
    manifest_path = snap / '完整快照哈希.json'
    assert sha(manifest_path) == risk['source_snapshot_sha256']
    name = 'batch/动态池单位收益与风险.parquet'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert sha(snap / name) == manifest['files'][name]
    old = [x for x in pq.read_table(snap / name).to_pylist() if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False]
    old_map = {(x['observation_id'], x['variant']): x for x in old}
    alt_map = {(x['observation_id'], x['variant'].replace('_1r_', '_2r_')): x for x in risk['records']
               if x.get('status') == x.get('risk_status') == 'verified' and x.get('liq_proxy') is False}
    gate_snap = P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
    gate_manifest = json.loads((gate_snap / '冻结哈希.json').read_text(encoding='utf-8'))
    csv_path = gate_snap / f'{year}一秒观察持仓量逐笔.csv'
    json_path = gate_snap / f'{year}一秒观察持仓量对照.json'
    assert sha(csv_path) == gate_manifest['files'][csv_path.name] and sha(json_path) == gate_manifest['files'][json_path.name]
    with csv_path.open(encoding='utf-8', newline='') as f:
        gate = {(x['observation_id'], x['variant']): x['gate'] for x in csv.DictReader(f)}
    gate_result = json.loads(json_path.read_text(encoding='utf-8'))
    checked = 0
    for out in result['rows']:
        lev, cohort, target, slip = out['leverage'], out['cohort'], out['exit_target'], out['exit_slippage_pct'] / 100
        variant = f'one_observation_2r_{lev}x'
        universe = [k for k in old_map if k[1] == variant and (cohort == 'base' or gate[k] == 'True')]
        paired = [k for k in universe if k in alt_map]
        prior = next(x for x in gate_result['rows'] if x['leverage'] == lev and x['strategy'] == cohort and x['exit_slippage_pct'] == .05)
        assert len(universe) == prior['known_trades'] == out['eligible_2r_trades']
        assert len(universe) - len(paired) == out['additional_unpaired_unknown']
        assert out['unknown_candidates'] == prior['unknown_candidates'] + len(universe) - len(paired)
        vals, days = [], set()
        for key in paired:
            r = alt_map[key] if target == '1r' else old_map[key]
            entry, side = float(r['entry_fill']), int(r['side'])
            exit_ = float(r['exit_raw']) * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r['funding']))
            days.add(datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(vals), sum(v > 0 for v in vals)
        positive = math.fsum(v for v in vals if v > 0)
        negative = -math.fsum(v for v in vals if v < 0)
        assert n == out['known_trades'] and wins == out['net_wins'] and len(days) == out['active_utc_days']
        assert near(100 * wins / n if n else None, out['net_win_rate_pct'])
        assert near(100 * math.fsum(vals) / n if n else None, out['mean_net_pct_notional'])
        assert near(positive / negative if negative else None, out['profit_factor'])
        assert near(100 * min(vals) if vals else None, out['worst_net_pct_notional'])
        checked += 1
    audit = {'all_checks_pass': True, 'year': year, 'groups_checked': checked, 'result_sha256': sha(result_file),
             'audit_code_sha256': sha(Path(__file__)), 'note': 'Independent arithmetic on audited matched entries, no account simulation.'}
    (H / f'{year}一倍止盈汇总独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_1R_SUMMARY_AUDIT', year, checked, flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2024', '2026')
    main(sys.argv[1])
