"""Evaluate the predeclared BTC-or-ETH OI condition on frozen unit paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
R69 = H.parent / '第六十九轮_一秒观察持仓量门'
sys.path.insert(0, str(R69))
from evaluate_2026_oi_gate import metrics


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == frozen['plan_sha256']
    result, detail = [], []
    for year in ('2024', '2026'):
        folder = R69 / f'{year}冻结结果'
        manifest = folder / '冻结哈希.json'
        assert sha(manifest) == frozen['oi_gate_snapshots'][year]
        info = json.loads(manifest.read_text(encoding='utf-8'))
        names = [f'{year}持仓量逐点核验.json', f'{year}一秒观察持仓量逐笔.csv', f'{year}一秒观察持仓量对照.json', f'{year}持仓量门独立核验.json']
        for name in names:
            assert sha(folder / name) == info['files'][name]
        point = json.loads((folder / names[0]).read_text(encoding='utf-8'))
        audit = json.loads((folder / names[3]).read_text(encoding='utf-8'))
        assert audit['all_checks_pass'] and audit['result_sha256'] == sha(folder / names[2])
        events = {x['observation_id']: x for x in point['events']}
        points = {(x['symbol'], int(x['ts'])): x for x in point['points']}
        with (folder / names[1]).open(encoding='utf-8', newline='') as f:
            ledger = list(csv.DictReader(f))
        previous = json.loads((folder / names[2]).read_text(encoding='utf-8'))
        records = []
        for r in ledger:
            e = events[r['observation_id']]
            decision, now, prior = int(e['decision_ts']), int(e['oi_t0']), int(e['oi_previous'])
            assert now == ((decision - 900000) // 300000) * 300000 and prior == now - 3600000
            flags = {}
            for symbol in ('BTCUSDT', 'ETHUSDT'):
                a, b = points.get((symbol, now)), points.get((symbol, prior))
                if not a or not b or a['status'] != 'verified' or b['status'] != 'verified':
                    flags[symbol] = None
                    continue
                x, y = D(str(a['values'][0])), D(str(b['values'][0]))
                assert x.is_finite() and y.is_finite() and x > 0 and y > 0
                flags[symbol] = x > y
            unknown = any(x is None for x in flags.values())
            count = None if unknown else sum(flags.values())
            and_gate = None if unknown else count == 2
            or_gate = None if unknown else count >= 1
            one = None if unknown else count == 1
            assert (r['gate'] == 'True') == (and_gate is True)
            if r['gate'] == '':
                assert and_gate is None
            side, entry = int(float(r['side'])), D(r['entry_fill'])
            raw, funding = D(r['exit_raw']), D(r['funding'])
            exit_ = raw * (1 - D(side) * D('.0005'))
            net = D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - funding
            assert abs(net - D(r['net'])) < D('1e-12')
            item = {'year': year, 'observation_id': r['observation_id'], 'variant': r['variant'], 'decision_ts': decision,
                    'oi_t0': now, 'oi_previous': prior, 'btc_up': flags['BTCUSDT'], 'eth_up': flags['ETHUSDT'],
                    'and_gate': and_gate, 'or_gate': or_gate, 'one_only': one,
                    'entry_ts': int(r['entry_ts']), 'entry_fill': entry, 'exit_raw': raw, 'side': side, 'funding': funding, 'net': net}
            records.append(item)
            detail.append(item)
        for lev in (10, 20):
            universe = [x for x in records if x['variant'].endswith(f'_{lev}x')]
            base = next(x for x in previous['rows'] if x['leverage'] == lev and x['strategy'] == 'base' and x['exit_slippage_pct'] == .05)
            assert len(universe) == base['known_trades']
            for cohort in ('base', 'and_gate', 'or_gate', 'one_only'):
                selected = universe if cohort == 'base' else [x for x in universe if x[cohort] is True]
                unknown = base['unknown_candidates'] + (sum(x[cohort] is None for x in universe) if cohort != 'base' else 0)
                no_order = base['known_no_order'] + (sum(x[cohort] is False for x in universe) if cohort != 'base' else 0)
                assert len(selected) + unknown + no_order == (119 if year == '2024' else 39)
                for slip in (D('.0005'), D('.00075'), D('.001')):
                    values = []
                    for r in selected:
                        exit_ = r['exit_raw'] * (1 - D(r['side']) * slip)
                        net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - r['funding']
                        values.append({**r, 'net': net})
                    result.append({'year': year, 'leverage': lev, 'cohort': cohort, 'exit_slippage_pct': float(100 * slip),
                                   **metrics(values, unknown), 'known_no_order': no_order})
            for old_name, cohort in (('base', 'base'), ('oi_gate', 'and_gate')):
                a = next(x for x in result if x['year'] == year and x['leverage'] == lev and x['cohort'] == cohort and x['exit_slippage_pct'] == .05)
                b = next(x for x in previous['rows'] if x['leverage'] == lev and x['strategy'] == old_name and x['exit_slippage_pct'] == .05)
                assert a['known_trades'] == b['known_trades'] and a['net_wins'] == b['net_wins']
                assert a['unknown_candidates'] == b['unknown_candidates'] and a['known_no_order'] == b['known_no_order']
                if a['known_trades']:
                    assert abs(a['mean_net_pct_notional'] - b['mean_net_pct_notional']) < 1e-10
    cols = ['year', 'observation_id', 'variant', 'decision_ts', 'oi_t0', 'oi_previous', 'btc_up', 'eth_up', 'and_gate', 'or_gate', 'one_only', 'entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding', 'net']
    with (H / '或条件逐笔明细.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(detail)
    output = {'rows': result, 'plan_sha256': sha(H / '冻结研究方案.md'), 'frozen_sha256': sha(H / '冻结时点.json'),
              'detail_sha256': sha(H / '或条件逐笔明细.csv'), 'code_sha256': sha(Path(__file__)),
              'note': 'Post-selection historical exploration; no live OI timing, account or actual fills.'}
    (H / '或条件跨期对照.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in result:
        if row['leverage'] == 20 and row['exit_slippage_pct'] == .05:
            print('OI_OR_RESULT', row, flush=True)


if __name__ == '__main__':
    main()
