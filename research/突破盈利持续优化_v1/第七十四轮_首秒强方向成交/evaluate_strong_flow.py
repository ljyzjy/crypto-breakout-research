"""Compare a fixed 0.50 one-second directional-imbalance gate."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent
R62 = P / '第六十二轮_一秒观察更早突破'
R69 = P / '第六十九轮_一秒观察持仓量门'
R73 = P / '第七十三轮_二零二三扩展核验'
sys.path.insert(0, str(R69))
from evaluate_2026_oi_gate import metrics


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def source_folders(year, frozen):
    if year in ('2024', '2026'):
        base, oi = R62 / f'{year}完整批次_冻结', R69 / f'{year}冻结结果'
        assert sha(base / '完整快照哈希.json') == frozen['base_snapshots'][year]
        assert sha(oi / '冻结哈希.json') == frozen['oi_snapshots'][year]
        oi_detail, oi_result = f'{year}一秒观察持仓量逐笔.csv', f'{year}一秒观察持仓量对照.json'
    else:
        base, oi = R73 / '2023基础冻结结果', R73 / '2023持仓量冻结结果'
        plan = json.loads((R73 / '冻结时点.json').read_text(encoding='utf-8'))
        assert sha(R73 / '冻结研究方案.md') == frozen['prior_2023_plan_sha256'] == plan['plan_sha256']
        oi_detail, oi_result = '2023一秒观察持仓量逐笔.csv', '2023持仓量跨期对照.json'
    return base, oi, oi_detail, oi_result


def main(year):
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == frozen['plan_sha256']
    base, oi, oi_detail, oi_result = source_folders(year, frozen)
    bm = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8'))
    om = json.loads((oi / '冻结哈希.json').read_text(encoding='utf-8'))
    assert bm['all_checks_pass'] and om['all_checks_pass']
    names = ['batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet', f'support/{year}一秒观察对照.json']
    for name in names:
        assert sha(base / name) == bm['files'][name]
    for name in (oi_detail, oi_result):
        assert sha(oi / name) == om['files'][name]
    signals = {x['observation_id']: x for x in pq.read_table(base / names[0]).to_pylist()}
    paths = [x for x in pq.read_table(base / names[1]).to_pylist() if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False]
    assert len({(x['observation_id'], x['variant']) for x in paths}) == len(paths)
    with (oi / oi_detail).open(encoding='utf-8', newline='') as f:
        gate = {(r['observation_id'], r['variant']): r['gate'] for r in csv.DictReader(f)}
    assert set(gate) == {(r['observation_id'], r['variant']) for r in paths}
    prior = json.loads((base / names[2]).read_text(encoding='utf-8'))
    oi_prior = json.loads((oi / oi_result).read_text(encoding='utf-8'))
    detail = []
    for row in paths:
        obs, variant = row['observation_id'], row['variant']
        s = signals[obs]
        assert s['status'] == 'qualified' and int(s['decision_ts']) == int(row['decision_ts'])
        side = int(row['side'])
        buy, sell = D(str(s['buy_notional'])), D(str(s['sell_notional']))
        assert buy >= 0 and sell >= 0 and buy + sell > 0 and int(s['one_count']) >= 3
        imbalance = D(side) * (buy - sell) / (buy + sell)
        assert abs(imbalance - D(str(s['one_imbalance']))) < D('1e-10') and imbalance >= D('.10') - D('1e-12')
        flow = imbalance >= D('.50')
        raw_gate = gate[(obs, variant)]
        assert raw_gate in ('True', 'False', '')
        oi_flag = None if raw_gate == '' else raw_gate == 'True'
        both = None if oi_flag is None else flow and oi_flag
        entry, raw, funding = D(str(row['entry_fill'])), D(str(row['exit_raw'])), D(str(row['funding']))
        exit_ = raw * (1 - D(side) * D('.0005'))
        net = D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - funding
        assert abs(net - D(str(row['net_per_unit_notional']))) < D('1e-11')
        detail.append({'observation_id': obs, 'variant': variant, 'decision_ts': int(row['decision_ts']),
                       'one_count': int(s['one_count']), 'buy_notional': buy, 'sell_notional': sell,
                       'side': side, 'imbalance': imbalance, 'strong_flow': flow, 'oi_gate': oi_flag, 'both': both,
                       'entry_ts': int(row['entry_ts']), 'entry_fill': entry, 'exit_raw': raw, 'funding': funding, 'net': net})
    expected_candidates = {'2023': 146, '2024': 119, '2026': 39}[year]
    results = []
    for lev in (10, 20):
        universe = [x for x in detail if x['variant'].endswith(f'_{lev}x')]
        baseline = next(x for x in prior['rows'] if x['leverage'] == lev)
        assert len(universe) == baseline['one_second_observation']['trades']
        for cohort in ('base', 'strong_flow', 'oi_gate', 'both'):
            chosen = universe if cohort == 'base' else [x for x in universe if x[cohort] is True]
            unknown = baseline['one_second_observation']['unknown'] + (sum(x[cohort] is None for x in universe) if cohort != 'base' else 0)
            no_order = baseline['known_no_order'] + (sum(x[cohort] is False for x in universe) if cohort != 'base' else 0)
            assert len(chosen) + unknown + no_order == expected_candidates
            for slip in (D('.0005'), D('.00075'), D('.001')):
                recs = []
                for r in chosen:
                    exit_ = r['exit_raw'] * (1 - D(r['side']) * slip)
                    net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - r['funding']
                    recs.append({**r, 'net': net})
                results.append({'year': year, 'leverage': lev, 'cohort': cohort, 'exit_slippage_pct': float(100 * slip),
                                **metrics(recs, unknown), 'known_no_order': no_order})
        for expected, cohort in (('base', 'base'), ('oi_gate', 'oi_gate')):
            x = next(z for z in results if z['leverage'] == lev and z['cohort'] == cohort and z['exit_slippage_pct'] == .05)
            y = next(z for z in oi_prior['rows'] if z['leverage'] == lev and z['strategy'] == expected and z['exit_slippage_pct'] == .05)
            assert x['known_trades'] == y['known_trades'] and x['net_wins'] == y['net_wins'] and x['unknown_candidates'] == y['unknown_candidates']
            if x['known_trades']:
                assert abs(x['mean_net_pct_notional'] - y['mean_net_pct_notional']) < 1e-10
    cols = ['observation_id', 'variant', 'decision_ts', 'one_count', 'buy_notional', 'sell_notional', 'side', 'imbalance',
            'strong_flow', 'oi_gate', 'both', 'entry_ts', 'entry_fill', 'exit_raw', 'funding', 'net']
    csv_path = H / f'{year}强方向逐笔.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(detail)
    out = {'year': year, 'rows': results, 'source_base_sha256': sha(base / '完整快照哈希.json'),
           'source_oi_sha256': sha(oi / '冻结哈希.json'), 'detail_sha256': sha(csv_path),
           'plan_sha256': sha(H / '冻结研究方案.md'), 'code_sha256': sha(Path(__file__)),
           'note': 'Post-selection historical exploration; no shared account or verified live execution.'}
    (H / f'{year}强方向对照.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in results:
        if row['leverage'] == 20 and row['exit_slippage_pct'] == .05:
            print('STRONG_FLOW_RESULT', row, flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
