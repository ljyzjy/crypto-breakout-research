"""Independently verify pre-entry sizing and realized illustrative trade risk."""
import csv
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def main():
    result_path, detail_path = H / '风险预算情景.json', H / '风险预算逐笔.csv'
    out = json.loads(result_path.read_text(encoding='utf-8'))
    assert out['plan_sha256'] == sha(H / '冻结研究方案.md') and out['code_sha256'] == sha(H / 'evaluate_budget.py')
    assert out['detail_sha256'] == sha(detail_path) and len(out['rows']) == 8
    with detail_path.open(encoding='utf-8', newline='') as f:
        details = list(csv.DictReader(f))
    assert len({(r['year'], r['leverage'], r['cohort'], r['observation_id']) for r in details}) == len(details)
    for year in ('2024', '2026'):
        base = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结'
        gate = P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
        manifest = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8'))
        gate_manifest = json.loads((gate / '冻结哈希.json').read_text(encoding='utf-8'))
        sig_path, ledger_path = base / 'batch/动态池逐笔信号筛查.parquet', base / 'batch/动态池单位收益与风险.parquet'
        gate_path = gate / f'{year}一秒观察持仓量逐笔.csv'
        assert sha(sig_path) == manifest['files']['batch/动态池逐笔信号筛查.parquet']
        assert sha(ledger_path) == manifest['files']['batch/动态池单位收益与风险.parquet']
        assert sha(gate_path) == gate_manifest['files'][gate_path.name]
        signals = {r['observation_id']: r for r in pq.read_table(sig_path).to_pylist()}
        ledger = {(r['observation_id'], r['variant']): r for r in pq.read_table(ledger_path).to_pylist()}
        with gate_path.open(encoding='utf-8', newline='') as f:
            flags = {(r['observation_id'], r['variant']): r['gate'] for r in csv.DictReader(f)}
        for row in (x for x in details if x['year'] == year):
            lev, obs, side = int(row['leverage']), row['observation_id'], int(row['side'])
            s, x = signals[obs], ledger[(obs, f'one_observation_2r_{lev}x')]
            assert x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False
            if row['cohort'] == 'oi_gate':
                assert flags[(obs, x['variant'])] == 'True'
            assert int(row['decision_ts']) == int(s['decision_ts']) and int(row['reference_ts']) == int(s['entry_exec_ts'])
            assert int(row['actual_entry_ts']) == int(x['entry_ts']) >= int(row['reference_ts']) + 1000
            ref, stop = float(s['raw_entry_1s']), float(s['stop_price'])
            assert near(ref, row['reference']) and near(stop, row['stop'])
            entry, stop_fill = ref * (1 + side * .0005), stop * (1 - side * .0005)
            loss_qty = -(side * (stop_fill - entry) - .0005 * entry - .0005 * stop_fill)
            qty = min(.005 / loss_qty, 1 / (entry * (1 / lev + .0005)))
            planned, estimate = qty * loss_qty, qty * entry * (1 / lev + .0005)
            actual_cost = qty * float(x['entry_fill']) * (1 / lev + .0005)
            realized = qty * float(x['entry_fill']) * float(x['net_per_unit_notional'])
            for field, value in [('estimated_entry', entry), ('estimated_stop_fill', stop_fill), ('planned_loss_per_qty', loss_qty),
                                 ('quantity_per_initial_equity', qty), ('planned_loss_fraction_equity', planned),
                                 ('estimated_initial_cost_fraction', estimate), ('actual_initial_cost_fraction', actual_cost),
                                 ('realized_fraction_equity', realized)]:
                assert near(row[field], value), (obs, field)
            assert planned <= .005 + 1e-12 and estimate <= 1 + 1e-12 and row['reason'] == x['reason']
    for row in out['rows']:
        group = [r for r in details if r['year'] == row['year'] and int(r['leverage']) == row['leverage'] and r['cohort'] == row['cohort']]
        vals = [float(r['realized_fraction_equity']) for r in group]
        assert len(group) == row['verified_trades']
        assert sum(x < -.005 - 1e-12 for x in vals) == row['loss_over_budget_count']
        assert sum(float(r['estimated_initial_cost_fraction']) >= 1 - 1e-12 for r in group) == row['cash_cap_binding_count']
        assert sum(float(r['actual_initial_cost_fraction']) > 1 + 1e-12 for r in group) == row['actual_initial_cost_over_equity_count']
        assert sum(r['reason'] == 'filled_beyond_risk_budget' for r in group) == row['risk_budget_breach_fill_count']
        assert near(100 * min(vals) if vals else None, row['worst_realized_pct_equity'])
        assert near(100 * math.fsum(vals) / len(vals) if vals else None, row['mean_realized_pct_equity'])
    audit = {'all_checks_pass': True, 'groups_checked': len(out['rows']), 'path_rows_checked': len(details),
             'result_sha256': sha(result_path), 'audit_code_sha256': sha(Path(__file__)),
             'note': 'Illustrative independent-trade sizing, not maximum account drawdown or a guaranteed loss cap.'}
    (H / '风险预算独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_RISK_BUDGET_AUDIT', len(out['rows']), len(details), flush=True)


if __name__ == '__main__':
    main()
