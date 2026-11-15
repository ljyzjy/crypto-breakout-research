"""Independently reconstruct all candidate classifications and summary statistics."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import replay_2022 as runner

H = Path(__file__).resolve().parent
B = H / '一秒回放批次'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def same(a, b):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def main():
    runner.guard(start=True)
    report_path = H / '二零二二一秒回测汇总.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    detail_path = H / '二零二二候选状态及单位账本.csv'
    assert report['code_sha256'] == sha(H / 'summarize_2022.py') and report['detail_sha256'] == sha(detail_path)
    signals = pd.read_parquet(B / '动态池逐笔信号筛查.parquet').set_index('observation_id').to_dict('index')
    paths = pd.read_parquet(B / '动态池延迟市价路径.parquet')
    ledger = pd.read_parquet(B / '动态池单位收益与风险.parquet')
    paths = {(r['observation_id'], r['holding_rule'], r['variant']): r for r in paths.to_dict('records')}
    ledger = {(r['observation_id'], r['holding_rule'], r['variant']): r for r in ledger.to_dict('records')}
    oi = json.loads((H / '持仓量逐点来源核验.json').read_text(encoding='utf-8'))
    events = {e['observation_id']: e for e in oi['events']}
    points = {(p['symbol'], int(p['ts'])): p for p in oi['points']}
    def reconstruct_oi(obs):
        event = events.get(obs)
        if not event: return None
        vals = []
        for symbol in ('BTCUSDT', 'ETHUSDT'):
            a, b = (points.get((symbol, int(event[k]))) for k in ('oi_t0', 'oi_previous'))
            if not a or not b or a['status'] != 'verified' or b['status'] != 'verified': return None
            vals.append(D(a['official_values'][0]) > D(b['official_values'][0]))
        return all(vals)
    detail = pd.read_csv(detail_path, dtype=str, keep_default_na=False)
    assert len(detail) == 310 * 2 * 2 * 4
    assert not detail.duplicated(['observation_id', 'holding_rule', 'leverage', 'cohort']).any()
    rows = {(r['holding_rule'], str(r['leverage']), r['cohort'], str(r['exit_slippage_pct'])): r for r in report['rows']}
    assert len(rows) == 48
    valid_signal = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}
    checked = 0
    for (holding, lev, cohort), g in detail.groupby(['holding_rule', 'leverage', 'cohort'], sort=True):
        assert len(g) == len(signals)
        categories, wins_by_slip, net_by_slip, days = Counter(), {}, {}, set()
        for x in g.to_dict('records'):
            s = signals[x['observation_id']]
            var = 'one_observation_2r_' + lev + 'x'
            key = (x['observation_id'], holding, var)
            status = s['status']
            if status not in valid_signal: expected = 'unknown'
            elif status != 'qualified': expected = 'no_order'
            elif pd.isna(s['precheck_' + lev + 'x']): expected = 'unknown'
            elif s['precheck_' + lev + 'x'] != 'passed': expected = 'no_order'
            elif key not in paths or paths[key]['status'] != 'verified': expected = 'unknown'
            elif key not in ledger or ledger[key]['risk_status'] != 'verified': expected = 'unknown'
            elif bool(ledger[key]['liq_proxy']): expected = 'unknown'
            else:
                side = int(s['side']); ref = D(str(s['raw_entry_1s'])); level = D(str(s['level']))
                assert side in (-1, 1) and ref > 0 and level > 0 and int(s['entry_exec_ts']) >= int(s['decision_ts']) + 1000
                distance_ok = D(0) < D(side) * (ref - level) / level <= D('.0005')
                oi_ok = reconstruct_oi(x['observation_id']) if cohort in ('oi', 'oi_distance') else True
                if oi_ok is None: expected = 'unknown'
                elif (cohort in ('distance', 'oi_distance') and not distance_ok) or not oi_ok: expected = 'no_order'
                else: expected = 'trade'
            assert x['category'] == expected, (x['observation_id'], holding, lev, cohort, x['category'], expected)
            categories[expected] += 1
            if expected == 'trade':
                r = ledger[key]; side = int(r['side']); fill = D(str(r['entry_fill'])); raw = D(str(r['exit_raw'])); fund = D(str(r['funding']))
                assert int(x['entry_ts']) == int(r['entry_ts']) and int(x['side']) == side
                assert int(r['entry_ts']) >= int(r['decision_ts']) + 2000 and int(r['exit_ts']) >= int(r['exit_signal_ts']) + 5000
                assert same(x['entry_fill'], fill) and same(x['exit_raw'], raw) and same(x['funding'], fund)
                days.add(pd.Timestamp(int(r['entry_ts']), unit='ms', tz='UTC').strftime('%Y-%m-%d'))
                for slip in ('0.05', '0.075', '0.1'):
                    ex = raw * (1 - D(side) * D(slip) / 100)
                    val = D(side) * (ex - fill) / fill - D('.0005') - D('.0005') * ex / fill - fund
                    net_by_slip.setdefault(slip, []).append(val)
                    if slip == '0.05': assert abs(val - D(x['net'])) < D('1e-11')
            checked += 1
        for slip in ('0.05', '0.075', '0.1'):
            row = rows[(holding, lev, cohort, slip)]
            vals = net_by_slip.get(slip, []); wins = [v for v in vals if v > 0]; losses = [v for v in vals if v < 0]
            assert row['candidate_events'] == 310 and row['trades'] == categories['trade'] == len(vals)
            assert row['known_no_order'] == categories['no_order'] and row['unknown_candidates'] == categories['unknown']
            assert row['net_wins'] == len(wins) and row['active_utc_days'] == len(days)
            assert same(row['net_win_rate_pct'], 100 * len(wins) / len(vals) if vals else None)
            assert same(row['average_net_pct_notional'], float(100 * sum(vals) / len(vals)) if vals else None)
            assert same(row['profit_factor'], float(sum(wins) / -sum(losses)) if losses else None)
    out = {'all_checks_pass': True, 'candidate_classifications_checked': checked, 'summary_groups_checked': len(rows),
           'report_sha256': sha(report_path), 'detail_sha256': sha(detail_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Reconstruction conditional on independently audited source paths; unknown rank hours remain outside candidate counts.'}
    (H / '二零二二汇总独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_SUMMARY_AUDIT_PASS', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
