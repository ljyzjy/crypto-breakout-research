"""Independently recompute OI truth values, candidate accounting, and returns."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent
R81 = H.parent / '第八十一轮_八至十月一秒观察'
D = Decimal


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '持仓量过滤对照.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'evaluate_oi.py') and result['frozen_sha256'] == sha(H / '冻结时点.json')
    assert result['oi_audit_sha256'] == sha(H / '持仓量逐点独立核验.json')
    assert result['base_summary_sha256'] == sha(R81 / '八至十月一秒观察结果.json')
    assert result['detail_sha256'] == sha(H / '持仓量过滤逐笔.csv')
    with (H / '持仓量过滤逐笔.csv').open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    with (R81 / '八至十月候选状态与账本.csv').open(encoding='utf-8', newline='') as f:
        base = {(x['observation_id'], int(x['leverage'])): x for x in csv.DictReader(f) if x['category'] == 'trade'}
    assert len(detail) == len(base) == 30
    point_data = json.loads((H / '持仓量逐点来源核验.json').read_text(encoding='utf-8'))
    events = {x['observation_id']: x for x in point_data['events']}
    points = {(x['symbol'], int(x['ts'])): x for x in point_data['points']}
    for row in detail:
        old = base[(row['observation_id'], int(row['leverage']))]
        for name in ('entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding', 'net'):
            assert near(row[name], old[name])
        e = events[row['observation_id']]
        decision = int(row['decision_ts'])
        now = ((decision - 900000) // 300000) * 300000
        previous = now - 3600000
        assert e['decision_ts'] == decision and int(row['oi_t0']) == now and int(row['oi_previous']) == previous
        flags = []
        for sym, field in (('BTCUSDT', 'btc_up'), ('ETHUSDT', 'eth_up')):
            a, b = points[(sym, now)], points[(sym, previous)]
            flag = None if a['status'] != 'verified' or b['status'] != 'verified' else D(a['official_values'][0]) > D(b['official_values'][0])
            assert row[field] == ('' if flag is None else str(flag))
            flags.append(flag)
        both = None if any(x is None for x in flags) else all(flags)
        assert row['oi_gate'] == ('' if both is None else str(both))
    old_result = json.loads((R81 / '八至十月一秒观察结果.json').read_text(encoding='utf-8'))
    assert len(result['rows']) == 12
    for r in result['rows']:
        lev, cohort, slip = r['leverage'], r['cohort'], r['exit_slippage_pct'] / 100
        universe = [x for x in detail if int(x['leverage']) == lev]
        selected = universe if cohort == 'base' else [x for x in universe if x['oi_gate'] == 'True']
        prev = next(x for x in old_result['rows'] if x['leverage'] == lev and x['exit_slippage_pct'] == .05)
        unknown = prev['unknown_candidates'] + (sum(x['oi_gate'] == '' for x in universe) if cohort == 'oi_gate' else 0)
        no_order = prev['known_no_order'] + (sum(x['oi_gate'] == 'False' for x in universe) if cohort == 'oi_gate' else 0)
        assert r['unknown_candidates'] == unknown and r['known_no_order'] == no_order and len(selected) + unknown + no_order == 57
        vals, days = [], set()
        for x in selected:
            side, entry, raw = int(x['side']), float(x['entry_fill']), float(x['exit_raw'])
            exit_ = raw * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(x['funding']))
            days.add(datetime.fromtimestamp(int(x['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(vals), sum(x > 0 for x in vals)
        pos, neg = math.fsum(x for x in vals if x > 0), -math.fsum(x for x in vals if x < 0)
        assert r['known_trades'] == n and r['net_wins'] == wins and r['active_utc_days'] == len(days)
        assert near(r['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(r['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(r['profit_factor'], pos / neg if neg else None)
    out = {'all_checks_pass': True, 'detail_rows_checked': len(detail), 'groups_checked': len(result['rows']),
           'result_sha256': sha(path), 'detail_sha256': sha(H / '持仓量过滤逐笔.csv'), 'code_sha256': sha(Path(__file__)),
           'note': 'Independent arithmetic of retrospective unit paths; not account outcomes.'}
    (H / '持仓量过滤独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT82_OI_EVALUATION_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
