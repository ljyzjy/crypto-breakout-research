"""Compare fixed BTC-and-ETH OI gate on audited Aug-Oct unit paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics

D = Decimal
getcontext().prec = 40


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    audit = json.loads((H / '持仓量逐点独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['source_sha256'] == sha(H / '持仓量逐点来源核验.json')
    assert audit['code_sha256'] == sha(H / 'audit_oi.py')
    source = json.loads((H / '持仓量逐点来源核验.json').read_text(encoding='utf-8'))
    events = {x['observation_id']: x for x in source['events']}
    points = {(x['symbol'], x['ts']): x for x in source['points']}
    prior = json.loads((R81 / '八至十月一秒观察结果.json').read_text(encoding='utf-8'))
    check = json.loads((R81 / '八至十月汇总独立核验.json').read_text(encoding='utf-8'))
    assert check['all_checks_pass'] and check['result_sha256'] == sha(R81 / '八至十月一秒观察结果.json')
    assert prior['detail_sha256'] == sha(R81 / '八至十月候选状态与账本.csv')
    with (R81 / '八至十月候选状态与账本.csv').open(encoding='utf-8', newline='') as f:
        original = list(csv.DictReader(f))
    detail, rows = [], []
    for r in original:
        if r['category'] != 'trade':
            continue
        e = events[r['observation_id']]
        assert e['oi_t0'] == ((int(e['decision_ts']) - 900000) // 300000) * 300000
        flags = {}
        for sym in ('BTCUSDT', 'ETHUSDT'):
            a, b = points[(sym, e['oi_t0'])], points[(sym, e['oi_previous'])]
            if a['status'] != 'verified' or b['status'] != 'verified':
                flags[sym] = None
            else:
                flags[sym] = D(a['official_values'][0]) > D(b['official_values'][0])
        gate = None if any(x is None for x in flags.values()) else all(flags.values())
        item = {'observation_id': r['observation_id'], 'leverage': int(r['leverage']), 'decision_ts': e['decision_ts'],
                'oi_t0': e['oi_t0'], 'oi_previous': e['oi_previous'], 'btc_up': flags['BTCUSDT'],
                'eth_up': flags['ETHUSDT'], 'oi_gate': gate, 'entry_ts': int(r['entry_ts']),
                'entry_fill': D(r['entry_fill']), 'exit_raw': D(r['exit_raw']), 'side': int(r['side']),
                'funding': D(r['funding']), 'net': D(r['net'])}
        detail.append(item)
    for lev in (10, 20):
        universe = [x for x in detail if x['leverage'] == lev]
        base = next(x for x in prior['rows'] if x['leverage'] == lev and x['exit_slippage_pct'] == .05)
        assert len(universe) == base['known_trades']
        for cohort in ('base', 'oi_gate'):
            selected = universe if cohort == 'base' else [x for x in universe if x['oi_gate'] is True]
            unknown = base['unknown_candidates'] + (sum(x['oi_gate'] is None for x in universe) if cohort == 'oi_gate' else 0)
            no_order = base['known_no_order'] + (sum(x['oi_gate'] is False for x in universe) if cohort == 'oi_gate' else 0)
            assert len(selected) + unknown + no_order == 57
            for slip in (D('.0005'), D('.00075'), D('.001')):
                paths = []
                for r in selected:
                    exit_ = r['exit_raw'] * (1 - D(r['side']) * slip)
                    net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - r['funding']
                    if slip == D('.0005'):
                        assert abs(net - r['net']) < D('1e-12')
                    paths.append({**r, 'net': net})
                rows.append({'leverage': lev, 'cohort': cohort, 'exit_slippage_pct': float(100 * slip),
                             **metrics(paths, unknown), 'known_no_order': no_order, 'candidate_events': 57})
        result = next(x for x in rows if x['leverage'] == lev and x['cohort'] == 'base' and x['exit_slippage_pct'] == .05)
        for key in ('known_trades', 'net_wins', 'unknown_candidates', 'known_no_order'):
            assert result[key] == base[key]
        assert abs(result['mean_net_pct_notional'] - base['mean_net_pct_notional']) < 1e-10
    names = ['observation_id', 'leverage', 'decision_ts', 'oi_t0', 'oi_previous', 'btc_up', 'eth_up', 'oi_gate',
             'entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding', 'net']
    csv_path = H / '持仓量过滤逐笔.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=names); writer.writeheader(); writer.writerows(detail)
    output = {'rows': rows, 'detail_sha256': sha(csv_path), 'oi_audit_sha256': sha(H / '持仓量逐点独立核验.json'),
              'base_summary_sha256': sha(R81 / '八至十月一秒观察结果.json'), 'frozen_sha256': sha(H / '冻结时点.json'),
              'code_sha256': sha(Path(__file__)), 'note': 'Retrospective small sample; not account or live execution.'}
    (H / '持仓量过滤对照.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for x in rows:
        if x['leverage'] == 20 and x['exit_slippage_pct'] == .05:
            print('EXT82_OI_RESULT', json.dumps(x, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
