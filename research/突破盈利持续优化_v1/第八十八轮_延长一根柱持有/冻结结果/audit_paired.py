"""Independently match unchanged/replayed exits and rederive every paired group."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
R86 = P / '第八十六轮_首秒追价距离过滤'
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '延长持有配对汇总.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'summarize_paired.py') and result['frozen_sha256'] == sha(H / '冻结时点.json')
    assert result['risk_ledger_sha256'] == sha(H / '延长持有风险账本.json')
    assert result['risk_audit_sha256'] == sha(H / '延长持有风险独立核验.json')
    assert result['tape_audit_sha256'] == sha(H / '延长持有逐笔独立核验.json')
    assert result['detail_sha256'] == sha(H / '延长持有配对逐笔.csv')
    with (H / '延长持有配对逐笔.csv').open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    with (R86 / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f:
        source = {(r['period'], r['observation_id'], r['variant']): r for r in csv.DictReader(f)}
    assert len(detail) == len(source) == 226
    original = json.loads((H / '原柱末退出回放输入.json').read_text(encoding='utf-8'))
    targets = {(e['period'], e['event']['observation_id'], p['variant']) for e in original['events'] for p in e['paths']}
    risk = json.loads((H / '延长持有风险账本.json').read_text(encoding='utf-8'))
    verified = {(r['period'], r['observation_id'], r['variant']): r for r in risk['records']}
    unknown = {(r['period'], r['observation_id'], r['variant']): r['status'] for r in risk['unknown']}
    assert len(targets) == 68 and set(verified).isdisjoint(unknown) and set(verified) | set(unknown) == targets
    assert {(r['period'], r['observation_id'], r['variant']) for r in detail} == set(source)
    for r in detail:
        key = r['period'], r['observation_id'], r['variant']
        old = source[key]
        for name in ('extension_gate', 'oi_gate', 'both', 'entry_ts', 'side'):
            assert r[name] == old[name]
        assert near(r['entry_fill'], old['entry_fill']) and near(r['old_exit_raw'], old['exit_raw']) and near(r['old_funding'], old['funding'])
        if key in verified:
            v = verified[key]
            assert r['new_status'] == 'verified' and r['new_reason'] == v['extended']['reason']
            assert near(r['new_exit_raw'], v['extended']['exit_raw']) and near(r['new_funding'], v['risk']['funding'])
        elif key in unknown:
            assert r['new_status'] == 'unknown' and r['new_reason'] == unknown[key]
            assert not r['new_exit_raw'] and not r['new_funding']
        else:
            assert r['new_status'] == 'verified' and r['new_reason'] == 'unchanged_original_exit'
            assert r['new_exit_raw'] == r['old_exit_raw'] and r['new_funding'] == r['old_funding']
    prior = json.loads((R86 / '首秒距离跨期对照.json').read_text(encoding='utf-8'))
    assert len(result['rows']) == 360
    for out in result['rows']:
        included = PERIODS if out['period'] == 'all' else (out['period'],)
        lev, cohort, mode, slip = out['leverage'], out['cohort'], out['comparison'], out['exit_slippage_pct'] / 100
        universe = [x for x in detail if x['period'] in included and x['variant'].endswith(f'_{lev}x')]
        selected = universe if cohort == 'base' else [x for x in universe if x[cohort] == 'True']
        common = selected if mode == 'original_all' else [x for x in selected if x['new_status'] == 'verified']
        baseline = next(x for x in prior['rows'] if x['period'] == out['period'] and x['leverage'] == lev and x['cohort'] == cohort and x['exit_slippage_pct'] == .05)
        new_unknown = len(selected) - len(common)
        assert out['additional_unknown'] == new_unknown and out['unknown_candidates'] == baseline['unknown_candidates'] + new_unknown
        assert out['known_no_order'] == baseline['known_no_order'] and out['candidate_events'] == baseline['candidate_events']
        assert len(common) + out['unknown_candidates'] + out['known_no_order'] == out['candidate_events']
        vals, days = [], set()
        for r in common:
            side, entry = int(r['side']), float(r['entry_fill'])
            raw = float(r['new_exit_raw'] if mode == 'extended' else r['old_exit_raw'])
            funding = float(r['new_funding'] if mode == 'extended' else r['old_funding'])
            exit_ = raw * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - funding)
            days.add(datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(vals), sum(x > 0 for x in vals)
        pos, neg = math.fsum(x for x in vals if x > 0), -math.fsum(x for x in vals if x < 0)
        assert out['known_trades'] == n and out['net_wins'] == wins and out['active_utc_days'] == len(days)
        assert near(out['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(out['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(out['profit_factor'], pos / neg if neg else None)
    out = {'all_checks_pass': True, 'detail_rows_checked': len(detail), 'groups_checked': len(result['rows']),
           'result_sha256': sha(path), 'detail_sha256': sha(H / '延长持有配对逐笔.csv'), 'code_sha256': sha(Path(__file__)),
           'note': 'Independent paired accounting on historical paths; no shared account or real execution.'}
    (H / '延长持有配对独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT88_PAIRED_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
