"""Apply the existing 0.5%-per-independent-trade sizing example to 1s paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

getcontext().prec = 36
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == frozen['plan_sha256'] and D(str(frozen['example_budget'])) == D('.005')
    results, details = [], []
    for year in ('2024', '2026'):
        base = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结'
        gate = P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
        bmfile, gmfile = base / '完整快照哈希.json', gate / '冻结哈希.json'
        assert sha(bmfile) == frozen['base_snapshots'][year] and sha(gmfile) == frozen['oi_snapshots'][year]
        bm, gm = json.loads(bmfile.read_text(encoding='utf-8')), json.loads(gmfile.read_text(encoding='utf-8'))
        signal_path, ledger_path = base / 'batch/动态池逐笔信号筛查.parquet', base / 'batch/动态池单位收益与风险.parquet'
        gate_path, gate_result = gate / f'{year}一秒观察持仓量逐笔.csv', gate / f'{year}一秒观察持仓量对照.json'
        for name, path in [('batch/动态池逐笔信号筛查.parquet', signal_path), ('batch/动态池单位收益与风险.parquet', ledger_path)]:
            assert sha(path) == bm['files'][name]
        for path in (gate_path, gate_result):
            assert sha(path) == gm['files'][path.name]
        signals = {r['observation_id']: r for r in pq.read_table(signal_path).to_pylist()}
        paths = [r for r in pq.read_table(ledger_path).to_pylist() if r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False]
        with gate_path.open(encoding='utf-8', newline='') as f:
            flags = {(x['observation_id'], x['variant']): x['gate'] for x in csv.DictReader(f)}
        assert set(flags) == {(r['observation_id'], r['variant']) for r in paths}
        prior = json.loads(gate_result.read_text(encoding='utf-8'))['rows']
        for lev in (10, 20):
            universe = [r for r in paths if r['variant'].endswith(f'_{lev}x')]
            for cohort in ('base', 'oi_gate'):
                group = universe if cohort == 'base' else [r for r in universe if flags[(r['observation_id'], r['variant'])] == 'True']
                reference_row = next(r for r in prior if r['leverage'] == lev and r['strategy'] == cohort and r['exit_slippage_pct'] == .05)
                assert len(group) == reference_row['known_trades']
                local = []
                for x in group:
                    s = signals[x['observation_id']]
                    side = D(int(x['side']))
                    ref, stop = D(str(s['raw_entry_1s'])), D(str(s['stop_price']))
                    assert int(s['entry_exec_ts']) >= int(s['decision_ts']) + 1000
                    assert int(x['entry_ts']) >= int(s['entry_exec_ts']) + 1000 and int(s['side']) == int(x['side'])
                    estimated_entry = ref * (1 + side * D('.0005'))
                    estimated_stop = stop * (1 - side * D('.0005'))
                    planned_loss_per_qty = -(side * (estimated_stop - estimated_entry) - D('.0005') * estimated_entry - D('.0005') * estimated_stop)
                    assert planned_loss_per_qty.is_finite() and planned_loss_per_qty > 0
                    qty_risk = D('.005') / planned_loss_per_qty
                    qty_cash = D(1) / (estimated_entry * (D(1) / lev + D('.0005')))
                    qty = min(qty_risk, qty_cash)
                    planned = qty * planned_loss_per_qty
                    est_cost = qty * estimated_entry * (D(1) / lev + D('.0005'))
                    actual_cost = qty * D(str(x['entry_fill'])) * (D(1) / lev + D('.0005'))
                    realized = qty * D(str(x['entry_fill'])) * D(str(x['net_per_unit_notional']))
                    assert planned <= D('.0050000000001') and est_cost <= D('1.00000000001')
                    item = {'year': year, 'leverage': lev, 'cohort': cohort, 'observation_id': x['observation_id'],
                            'decision_ts': int(s['decision_ts']), 'reference_ts': int(s['entry_exec_ts']), 'actual_entry_ts': int(x['entry_ts']),
                            'side': int(side), 'reference': ref, 'stop': stop, 'estimated_entry': estimated_entry,
                            'estimated_stop_fill': estimated_stop, 'planned_loss_per_qty': planned_loss_per_qty,
                            'quantity_per_initial_equity': qty, 'planned_loss_fraction_equity': planned,
                            'estimated_initial_cost_fraction': est_cost, 'actual_initial_cost_fraction': actual_cost,
                            'realized_fraction_equity': realized, 'actual_entry_fill': D(str(x['entry_fill'])),
                            'net_per_unit_notional': D(str(x['net_per_unit_notional'])), 'reason': x['reason']}
                    local.append(item)
                    details.append(item)
                vals = [x['realized_fraction_equity'] for x in local]
                results.append({'year': year, 'leverage': lev, 'cohort': cohort, 'verified_trades': len(local),
                                'unknown_candidates': reference_row['unknown_candidates'], 'risk_budget_pct_equity': .5,
                                'loss_over_budget_count': sum(x < D('-.005000000001') for x in vals),
                                'cash_cap_binding_count': sum(x['estimated_initial_cost_fraction'] >= D('.999999999999') for x in local),
                                'actual_initial_cost_over_equity_count': sum(x['actual_initial_cost_fraction'] > D('1.000000000001') for x in local),
                                'risk_budget_breach_fill_count': sum(x['reason'] == 'filled_beyond_risk_budget' for x in local),
                                'worst_realized_pct_equity': float(D(100) * min(vals)) if vals else None,
                                'mean_realized_pct_equity': float(D(100) * sum(vals) / len(vals)) if vals else None})
    fields = ['year', 'leverage', 'cohort', 'observation_id', 'decision_ts', 'reference_ts', 'actual_entry_ts', 'side', 'reference', 'stop',
              'estimated_entry', 'estimated_stop_fill', 'planned_loss_per_qty', 'quantity_per_initial_equity', 'planned_loss_fraction_equity',
              'estimated_initial_cost_fraction', 'actual_initial_cost_fraction', 'realized_fraction_equity', 'actual_entry_fill', 'net_per_unit_notional', 'reason']
    detail_path = H / '风险预算逐笔.csv'
    with detail_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(details)
    out = {'rows': results, 'plan_sha256': sha(H / '冻结研究方案.md'), 'frozen_sha256': sha(H / '冻结时点.json'),
           'detail_sha256': sha(detail_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Illustrative independent trade sizing; no shared account, actual orders, or guaranteed maximum loss.'}
    (H / '风险预算情景.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in results:
        if row['leverage'] == 20:
            print('ONEOBS_RISK_BUDGET', row, flush=True)


if __name__ == '__main__':
    main()
