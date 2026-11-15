"""Compare one fixed one-second distance gate with existing frozen paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

from extension_gate import gate

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
R82 = P / '第八十二轮_八至十月持仓量过滤'
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics

getcontext().prec = 40
D = Decimal
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][name]
    test = json.loads((H / '追价距离合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['gate_sha256'] == sha(H / 'extension_gate.py')
    assert test['test_code_sha256'] == sha(H / 'test_extension_gate.py')
    old = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    detail, baseline = [], {}
    for period in PERIODS:
        if period == '2026_aug_oct':
            base, oi = R81 / '冻结结果', R82 / '冻结结果'
            bm, om = base / '冻结哈希.json', oi / '冻结哈希.json'
            assert sha(bm) == frozen['sources_sha256']['r81_freeze'] and sha(om) == frozen['sources_sha256']['r82_freeze']
            oi_csv, oi_json = '持仓量过滤逐笔.csv', '持仓量过滤对照.json'
        else:
            base = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            oi = P / ('第七十三轮_二零二三扩展核验/2023持仓量冻结结果' if period == '2023' else f'第六十九轮_一秒观察持仓量门/{period}冻结结果')
            bm, om = base / '完整快照哈希.json', oi / '冻结哈希.json'
            assert sha(bm) == old['base_snapshots'][period] and sha(om) == old['oi_snapshots'][period]
            oi_csv = f'{period}一秒观察持仓量逐笔.csv'
            oi_json = f'{period}持仓量跨期对照.json' if period == '2023' else f'{period}一秒观察持仓量对照.json'
        bmeta, ometa = json.loads(bm.read_text(encoding='utf-8')), json.loads(om.read_text(encoding='utf-8'))
        assert bmeta['all_checks_pass'] and ometa['all_checks_pass']
        sn, pn = 'batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet'
        assert sha(base / sn) == bmeta['files'][sn] and sha(base / pn) == bmeta['files'][pn]
        assert sha(oi / oi_csv) == ometa['files'][oi_csv] and sha(oi / oi_json) == ometa['files'][oi_json]
        signal = {r['observation_id']: r for r in pq.read_table(base / sn).to_pylist()}
        paths = [r for r in pq.read_table(base / pn).to_pylist() if r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False]
        with (oi / oi_csv).open(encoding='utf-8', newline='') as f:
            gate_map = {}
            for r in csv.DictReader(f):
                if period == '2026_aug_oct':
                    key, value = (r['observation_id'], f"one_observation_2r_{r['leverage']}x"), r['oi_gate']
                else:
                    key, value = (r['observation_id'], r['variant']), r['gate']
                assert value in ('True', 'False', '') and key not in gate_map
                gate_map[key] = None if value == '' else value == 'True'
        assert set(gate_map) == {(r['observation_id'], r['variant']) for r in paths}
        result = json.loads((oi / oi_json).read_text(encoding='utf-8'))
        for lev in (10, 20):
            def get_prior(which):
                if period == '2026_aug_oct':
                    return next(x for x in result['rows'] if x['leverage'] == lev and x['cohort'] == which and x['exit_slippage_pct'] == .05)
                return next(x for x in result['rows'] if x['leverage'] == lev and x['strategy'] == which and x['exit_slippage_pct'] == .05)
            baseline[(period, lev)] = {'base': get_prior('base'), 'oi_gate': get_prior('oi_gate')}
        for r in paths:
            s = signal[r['observation_id']]
            assert s['status'] == 'qualified' and int(s['decision_ts']) == int(r['decision_ts'])
            assert int(s['entry_exec_ts']) == int(r['entry_signal_reference_ts']) and int(s['side']) == int(r['side'])
            extension, distance = gate(s)
            oi_flag = gate_map[(r['observation_id'], r['variant'])]
            both = None if extension is None or oi_flag is None else extension and oi_flag
            side, entry, raw, funding = int(r['side']), D(str(r['entry_fill'])), D(str(r['exit_raw'])), D(str(r['funding']))
            exit_ = raw * (1 - D(side) * D('.0005'))
            net = D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - funding
            assert abs(net - D(str(r['net_per_unit_notional']))) < D('1e-11')
            detail.append({'period': period, 'observation_id': r['observation_id'], 'variant': r['variant'],
                           'decision_ts': int(s['decision_ts']), 'reference_ts': int(s['entry_exec_ts']),
                           'side': side, 'reference': D(str(s['raw_entry_1s'])), 'level': D(str(s['level'])),
                           'distance': distance, 'extension_gate': extension, 'oi_gate': oi_flag, 'both': both,
                           'entry_ts': int(r['entry_ts']), 'entry_fill': entry, 'exit_raw': raw, 'funding': funding, 'net': net})
    assert len(detail) == 226
    results = []
    for period in (*PERIODS, 'all'):
        included = PERIODS if period == 'all' else (period,)
        for lev in (10, 20):
            universe = [x for x in detail if x['period'] in included and x['variant'].endswith(f'_{lev}x')]
            original_unknown = sum(baseline[(p, lev)]['base']['unknown_candidates'] for p in included)
            original_no_order = sum(baseline[(p, lev)]['base']['known_no_order'] for p in included)
            total = sum(baseline[(p, lev)]['base']['candidate_events'] if 'candidate_events' in baseline[(p, lev)]['base'] else
                        baseline[(p, lev)]['base']['known_trades'] + baseline[(p, lev)]['base']['unknown_candidates'] + baseline[(p, lev)]['base']['known_no_order'] for p in included)
            for cohort in ('base', 'extension_gate', 'oi_gate', 'both'):
                selected = universe if cohort == 'base' else [x for x in universe if x[cohort] is True]
                unknown = original_unknown + (sum(x[cohort] is None for x in universe) if cohort != 'base' else 0)
                no_order = original_no_order + (sum(x[cohort] is False for x in universe) if cohort != 'base' else 0)
                assert len(selected) + unknown + no_order == total
                for slip in (D('.0005'), D('.00075'), D('.001')):
                    paths = []
                    for r in selected:
                        exit_ = r['exit_raw'] * (1 - D(r['side']) * slip)
                        net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - r['funding']
                        paths.append({**r, 'net': net})
                    results.append({'period': period, 'leverage': lev, 'cohort': cohort, 'exit_slippage_pct': float(100 * slip),
                                    **metrics(paths, unknown), 'known_no_order': no_order, 'candidate_events': total})
            if period != 'all':
                for cohort in ('base', 'oi_gate'):
                    a = next(x for x in results if x['period'] == period and x['leverage'] == lev and x['cohort'] == cohort and x['exit_slippage_pct'] == .05)
                    b = baseline[(period, lev)][cohort]
                    for name in ('known_trades', 'net_wins', 'unknown_candidates', 'known_no_order'):
                        assert a[name] == b[name]
                    if a['known_trades']:
                        assert abs(a['mean_net_pct_notional'] - b['mean_net_pct_notional']) < 1e-10
    fields = ['period', 'observation_id', 'variant', 'decision_ts', 'reference_ts', 'side', 'reference', 'level',
              'distance', 'extension_gate', 'oi_gate', 'both', 'entry_ts', 'entry_fill', 'exit_raw', 'funding', 'net']
    path = H / '首秒距离逐笔.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(detail)
    out = {'rows': results, 'detail_sha256': sha(path), 'frozen_sha256': sha(H / '冻结时点.json'),
           'test_sha256': sha(H / '追价距离合成核验.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'One fixed gate on previously studied unequal periods; not blind or account results.'}
    (H / '首秒距离跨期对照.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in results:
        if r['leverage'] == 20 and r['exit_slippage_pct'] == .05:
            print('EXT86_RESULT', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
