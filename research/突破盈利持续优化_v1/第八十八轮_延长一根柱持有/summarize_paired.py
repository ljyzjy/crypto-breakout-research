"""Pair original vs one-extra-quarter exit across all frozen candidate cohorts."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
R86 = P / '第八十六轮_首秒追价距离过滤'
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics

D = Decimal
getcontext().prec = 40
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    risk_audit = json.loads((H / '延长持有风险独立核验.json').read_text(encoding='utf-8'))
    tape_audit = json.loads((H / '延长持有逐笔独立核验.json').read_text(encoding='utf-8'))
    assert risk_audit['all_checks_pass'] and risk_audit['source_sha256'] == sha(H / '延长持有风险账本.json')
    assert tape_audit['all_checks_pass'] and tape_audit['code_sha256'] == sha(H / 'audit_tape_samples.py')
    assert risk_audit['code_sha256'] == sha(H / 'audit_risk.py')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    assert sha(R86 / '首秒距离逐笔.csv') == frozen['sources_sha256']['r86_detail']
    assert sha(R86 / '首秒距离独立核验.json') == frozen['sources_sha256']['r86_audit']
    prior = json.loads((R86 / '首秒距离跨期对照.json').read_text(encoding='utf-8'))
    original = json.loads((H / '原柱末退出回放输入.json').read_text(encoding='utf-8'))
    targeted = {(e['period'], e['event']['observation_id'], p['variant']) for e in original['events'] for p in e['paths']}
    risk = json.loads((H / '延长持有风险账本.json').read_text(encoding='utf-8'))
    extended = {(x['period'], x['observation_id'], x['variant']): x for x in risk['records']}
    unknown = {(x['period'], x['observation_id'], x['variant']): x['status'] for x in risk['unknown']}
    assert len(targeted) == 68 and set(extended).isdisjoint(unknown) and set(extended) | set(unknown) == targeted
    with (R86 / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f:
        source = list(csv.DictReader(f))
    detail = []
    for r in source:
        key = r['period'], r['observation_id'], r['variant']
        side, entry, old_raw, old_fund = int(r['side']), D(r['entry_fill']), D(r['exit_raw']), D(r['funding'])
        old_exit = old_raw * (1 - D(side) * D('.0005'))
        old_net = D(side) * (old_exit - entry) / entry - D('.0005') - D('.0005') * old_exit / entry - old_fund
        assert abs(old_net - D(r['net'])) < D('1e-11')
        if key in extended:
            x = extended[key]
            assert abs(D(str(x['original']['net_per_unit_notional'])) - old_net) < D('1e-11')
            new_raw, new_fund = D(str(x['extended']['exit_raw'])), D(str(x['risk']['funding']))
            new_status, new_reason = 'verified', x['extended']['reason']
        elif key in targeted:
            new_raw, new_fund, new_status, new_reason = None, None, 'unknown', unknown[key]
        else:
            new_raw, new_fund, new_status, new_reason = old_raw, old_fund, 'verified', 'unchanged_original_exit'
        detail.append({'period': r['period'], 'observation_id': r['observation_id'], 'variant': r['variant'],
                       'extension_gate': r['extension_gate'], 'oi_gate': r['oi_gate'], 'both': r['both'],
                       'entry_ts': int(r['entry_ts']), 'side': side, 'entry_fill': entry,
                       'old_exit_raw': old_raw, 'old_funding': old_fund, 'new_status': new_status,
                       'new_exit_raw': new_raw, 'new_funding': new_fund, 'new_reason': new_reason})
    assert len(detail) == 226
    results = []
    for period in (*PERIODS, 'all'):
        included = PERIODS if period == 'all' else (period,)
        for lev in (10, 20):
            universe = [r for r in detail if r['period'] in included and r['variant'].endswith(f'_{lev}x')]
            for cohort in ('base', 'extension_gate', 'oi_gate', 'both'):
                selected = universe if cohort == 'base' else [r for r in universe if r[cohort] == 'True']
                common = [r for r in selected if r['new_status'] == 'verified']
                previous = next(x for x in prior['rows'] if x['period'] == period and x['leverage'] == lev and x['cohort'] == cohort and x['exit_slippage_pct'] == .05)
                additional_unknown = len(selected) - len(common)
                assert len(selected) == previous['known_trades']
                for comparison in ('original_all', 'original_paired', 'extended'):
                    sample = selected if comparison == 'original_all' else common
                    unknown_count = previous['unknown_candidates'] + (additional_unknown if comparison != 'original_all' else 0)
                    assert len(sample) + unknown_count + previous['known_no_order'] == previous['candidate_events']
                    for slip in (D('.0005'), D('.00075'), D('.001')):
                        vals = []
                        for r in sample:
                            raw = r['new_exit_raw'] if comparison == 'extended' else r['old_exit_raw']
                            funding = r['new_funding'] if comparison == 'extended' else r['old_funding']
                            exit_ = raw * (1 - D(r['side']) * slip)
                            net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - funding
                            vals.append({**r, 'net': net})
                        results.append({'period': period, 'leverage': lev, 'cohort': cohort, 'comparison': comparison,
                                        'exit_slippage_pct': float(100 * slip), **metrics(vals, unknown_count),
                                        'known_no_order': previous['known_no_order'], 'candidate_events': previous['candidate_events'],
                                        'additional_unknown': additional_unknown if comparison != 'original_all' else 0})
                default = next(x for x in results if x['period'] == period and x['leverage'] == lev and x['cohort'] == cohort and x['comparison'] == 'original_all' and x['exit_slippage_pct'] == .05)
                assert default['known_trades'] == previous['known_trades'] and default['net_wins'] == previous['net_wins']
                if default['known_trades']:
                    assert abs(default['mean_net_pct_notional'] - previous['mean_net_pct_notional']) < 1e-10
    fields = ['period', 'observation_id', 'variant', 'extension_gate', 'oi_gate', 'both', 'entry_ts', 'side', 'entry_fill',
              'old_exit_raw', 'old_funding', 'new_status', 'new_exit_raw', 'new_funding', 'new_reason']
    path = H / '延长持有配对逐笔.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(detail)
    out = {'rows': results, 'detail_sha256': sha(path), 'tape_audit_sha256': sha(H / '延长持有逐笔独立核验.json'),
           'risk_audit_sha256': sha(H / '延长持有风险独立核验.json'), 'risk_ledger_sha256': sha(H / '延长持有风险账本.json'),
           'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Historical paired unit opportunities only; previously studied periods and incomplete candidates.'}
    (H / '延长持有配对汇总.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in results:
        if r['period'] in ('all', '2026_aug_oct') and r['leverage'] == 20 and r['comparison'] in ('original_paired', 'extended') and r['exit_slippage_pct'] == .05:
            print('EXT88_RESULT', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
