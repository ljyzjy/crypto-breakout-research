"""Post-hoc decomposition of audited 2R paths into price, fees and slippage."""
from collections import Counter
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import statistics

import pyarrow.parquet as pq

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    output, details = [], []
    for year in ('2024', '2026'):
        base = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结'
        gate = P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
        bm = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8'))
        gm = json.loads((gate / '冻结哈希.json').read_text(encoding='utf-8'))
        ledger_path = base / 'batch/动态池单位收益与风险.parquet'
        gate_path = gate / f'{year}一秒观察持仓量逐笔.csv'
        assert sha(ledger_path) == bm['files']['batch/动态池单位收益与风险.parquet']
        assert sha(gate_path) == gm['files'][gate_path.name]
        with gate_path.open(encoding='utf-8', newline='') as f:
            flags = {(x['observation_id'], x['variant']): x['gate'] for x in csv.DictReader(f)}
        rows = [x for x in pq.read_table(ledger_path).to_pylist() if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False]
        assert set(flags) == {(x['observation_id'], x['variant']) for x in rows}
        for r in rows:
            side = D(int(r['side']))
            raw_in, actual_in, raw_out, actual_out = (D(str(r[x])) for x in ('entry_raw', 'entry_fill', 'exit_raw', 'exit_fill'))
            gross = side * (raw_out - raw_in) / actual_in
            entry_slip = side * (raw_in - actual_in) / actual_in
            exit_slip = side * (actual_out - raw_out) / actual_in
            fees = -D(str(r['entry_fee'])) - D(str(r['exit_fee']))
            funding = -D(str(r['funding']))
            net = gross + entry_slip + exit_slip + fees + funding
            assert abs(net - D(str(r['net_per_unit_notional']))) < D('1e-11')
            details.append({'year': year, 'observation_id': r['observation_id'], 'variant': r['variant'],
                            'oi_gate': flags[(r['observation_id'], r['variant'])], 'entry_ts': int(r['entry_ts']),
                            'exit_ts': int(r['exit_ts']), 'reason': r['reason'], 'gross': gross,
                            'entry_slip': entry_slip, 'exit_slip': exit_slip, 'fees': fees, 'funding': funding, 'net': net})
        for lev in (10, 20):
            universe = [r for r in details if r['year'] == year and r['variant'].endswith(f'_{lev}x')]
            for cohort in ('base', 'oi_gate'):
                group = universe if cohort == 'base' else [r for r in universe if r['oi_gate'] == 'True']
                n = len(group)
                assert n
                means = {f'mean_{k}_pct_notional': float(D(100) * sum((r[k] for r in group), D(0)) / n)
                         for k in ('gross', 'entry_slip', 'exit_slip', 'fees', 'funding', 'net')}
                output.append({'year': year, 'leverage': lev, 'cohort': cohort, 'trades': n,
                               **means, 'exit_reasons': dict(Counter(r['reason'] for r in group)),
                               'median_holding_seconds': statistics.median((r['exit_ts'] - r['entry_ts']) / 1000 for r in group)})
    fields = ['year', 'observation_id', 'variant', 'oi_gate', 'entry_ts', 'exit_ts', 'reason', 'gross', 'entry_slip', 'exit_slip', 'fees', 'funding', 'net']
    path = H / '成本归因逐笔.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(details)
    out = {'rows': output, 'detail_sha256': sha(path), 'code_sha256': sha(Path(__file__)),
           'note': 'Post-hoc arithmetic on known unit paths, not account equity or actual fills.'}
    (H / '成本与退出原因诊断.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    for r in output:
        if r['leverage'] == 20:
            print('COST_ATTRIBUTION', r, flush=True)


if __name__ == '__main__':
    main()
