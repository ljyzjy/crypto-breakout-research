"""Apply the previously fixed dual-OI gate to audited 2023 paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent
SNAP = H / '2023基础冻结结果'
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    point_file = H / '2023持仓量逐点核验.json'
    point = json.loads(point_file.read_text(encoding='utf-8'))
    assert point['plan_sha256'] == sha(H / '冻结研究方案.md') and point['code_sha256'] == sha(H / 'prepare_2023_oi.py')
    source_audit = json.loads((H / '2023持仓量来源独立核验.json').read_text(encoding='utf-8'))
    assert source_audit['all_checks_pass'] and source_audit['point_input_sha256'] == sha(point_file)
    assert source_audit['audit_code_sha256'] == sha(H / 'audit_2023_oi_sources.py')
    ledger_file = H / '2023一秒观察已核验账本.csv'
    assert point['ledger_csv_sha256'] == sha(ledger_file)
    manifest_file = SNAP / '完整快照哈希.json'
    assert point['snapshot_manifest_sha256'] == sha(manifest_file)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    assert manifest['all_checks_pass']
    events = {x['observation_id']: x for x in point['events']}
    points = {(x['symbol'], int(x['ts'])): x for x in point['points']}
    assert len(events) == len(point['events']) and len(points) == len(point['points'])
    with ledger_file.open(encoding='utf-8', newline='') as f:
        ledger = list(csv.DictReader(f))
    assert len({(x['observation_id'], x['variant']) for x in ledger}) == len(ledger)
    detail = []
    for row in ledger:
        obs = row['observation_id']
        event = events[obs]
        decision, now, prior = int(event['decision_ts']), int(event['oi_t0']), int(event['oi_previous'])
        assert int(float(row['decision_ts'])) == decision and now == (decision - 900000) // 300000 * 300000 and prior == now - 3600000
        values = {}
        status = 'verified'
        for sym in ('BTCUSDT', 'ETHUSDT'):
            a, b = points.get((sym, now)), points.get((sym, prior))
            if not a or not b or a['status'] != 'verified' or b['status'] != 'verified':
                status = 'unknown_oi'
                continue
            x, y = D(str(a['values'][0])), D(str(b['values'][0]))
            assert x.is_finite() and y.is_finite() and x > 0 and y > 0
            values[sym] = x / y - 1
        gate = all(values[s] > 0 for s in ('BTCUSDT', 'ETHUSDT')) if status == 'verified' else None
        side, entry, raw = int(float(row['side'])), D(row['entry_fill']), D(row['exit_raw'])
        exit_ = raw * (1 - D(side) * D('.0005'))
        net = D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - D(row['funding'])
        assert abs(net - D(row['net_per_unit_notional'])) < D('1e-12')
        detail.append({'observation_id': obs, 'variant': row['variant'], 'decision_ts': decision, 'oi_t0': now,
                       'oi_previous': prior, 'oi_status': status, 'gate': gate,
                       'btc_change': float(values['BTCUSDT']) if 'BTCUSDT' in values else None,
                       'eth_change': float(values['ETHUSDT']) if 'ETHUSDT' in values else None,
                       'entry_ts': int(row['entry_ts']), 'entry_fill': entry, 'exit_raw': raw, 'side': side,
                       'funding': D(row['funding']), 'net': net})
    previous = json.loads((SNAP / 'support/2023一秒观察对照.json').read_text(encoding='utf-8'))
    results = []
    for lev in (10, 20):
        universe = [x for x in detail if x['variant'] == f'one_observation_2r_{lev}x']
        baseline = next(x for x in previous['rows'] if x['leverage'] == lev)
        assert len(universe) == baseline['one_second_observation']['trades']
        for strategy in ('base', 'oi_gate'):
            chosen = universe if strategy == 'base' else [x for x in universe if x['gate'] is True]
            unknown = baseline['one_second_observation']['unknown'] + (sum(x['gate'] is None for x in universe) if strategy == 'oi_gate' else 0)
            no_order = baseline['known_no_order'] + (sum(x['gate'] is False for x in universe) if strategy == 'oi_gate' else 0)
            assert len(chosen) + unknown + no_order == 146
            for slip in (D('.0005'), D('.00075'), D('.001')):
                records = []
                for r in chosen:
                    exit_ = r['exit_raw'] * (1 - D(r['side']) * slip)
                    net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - r['funding']
                    records.append({**r, 'net': net})
                results.append({'leverage': lev, 'strategy': strategy, 'exit_slippage_pct': float(100 * slip),
                                **metrics(records, unknown), 'known_no_order': no_order})
        base = next(x for x in results if x['leverage'] == lev and x['strategy'] == 'base' and x['exit_slippage_pct'] == .05)
        ref = baseline['one_second_observation']
        assert base['known_trades'] == ref['trades'] and base['net_wins'] == ref['wins']
        if base['known_trades']:
            assert abs(base['mean_net_pct_notional'] - ref['mean_net_pct_notional']) < 1e-10
    cols = ['observation_id', 'variant', 'decision_ts', 'oi_t0', 'oi_previous', 'oi_status', 'gate', 'btc_change', 'eth_change', 'entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding', 'net']
    csv_path = H / '2023一秒观察持仓量逐笔.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(detail)
    output = {'year': '2023', 'rows': results, 'original_unknown_candidates': 19,
              'inputs': {'point_audit_sha256': sha(point_file), 'ledger_csv_sha256': sha(ledger_file), 'detail_sha256': sha(csv_path),
                         'plan_sha256': sha(H / '冻结研究方案.md'), 'code_sha256': sha(Path(__file__))},
              'note': 'Previously explored historical period; no account simulation or verified live OI arrival.'}
    (H / '2023持仓量跨期对照.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in results:
        if row['leverage'] == 20 and row['exit_slippage_pct'] == .05:
            print('YEAR2023_OI_RESULT', row, flush=True)


if __name__ == '__main__':
    main()
