"""Evaluate the frozen first-five-minute gate on audited existing trade paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R90 = P / '第九十轮_二零二二公开行情'
R86 = P / '第八十六轮_首秒追价距离过滤'
R88 = P / '第八十八轮_延长一根柱持有'
sys.path.insert(0, str(R90))
import run_wallet_2022 as wallet90
D = Decimal
getcontext().prec = 40
Q, FIVE = 900000, 300000
PERIODS = ('2022', '2023', '2024', '2026', '2026_aug_oct')
COHORTS = ('base', 'distance', 'oi', 'oi_distance')


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def net(side, entry, raw, funding, slip):
    ex = raw * (1 - D(side) * slip)
    return D(side) * (ex - entry) / entry - D('.0005') - D('.0005') * ex / entry - funding


def metrics(records, slip):
    values = [net(r['side'], r['entry_fill'], r['exit_raw'], r['funding'], slip) for r in records]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    days = {pd.Timestamp(r['entry_ts'], unit='ms', tz='UTC').strftime('%Y-%m-%d') for r in records}
    return {'known_trades': len(values), 'net_wins': len(wins),
            'net_win_rate_pct': float(D(100) * len(wins) / len(values)) if values else None,
            'mean_net_pct_notional': float(D(100) * sum(values) / len(values)) if values else None,
            'profit_factor': float(sum(wins) / -sum(losses)) if losses else None,
            'active_utc_days': len(days)}


def main():
    wallet90.runner.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and not frozen['2022_pnl_viewed_before_freeze']
    for name, path in frozen['source_paths'].items(): assert sha(Path(path)) == frozen['source_sha256'][name]
    audit90 = json.loads((R90 / '二零二二汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit90['all_checks_pass'] and audit90['report_sha256'] == sha(R90 / '二零二二一秒回测汇总.json')
    assert audit90['detail_sha256'] == sha(R90 / '二零二二候选状态及单位账本.csv')
    audit86 = json.loads((R86 / '首秒距离独立核验.json').read_text(encoding='utf-8'))
    audit88 = json.loads((R88 / '延长持有配对独立核验.json').read_text(encoding='utf-8'))
    assert audit86['all_checks_pass'] and audit88['all_checks_pass']
    with (R86 / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f: older = list(csv.DictReader(f))
    with (R88 / '延长持有配对逐笔.csv').open(encoding='utf-8', newline='') as f: later = list(csv.DictReader(f))
    paired = {(x['period'], x['observation_id'], x['variant']): x for x in later}
    assert len(older) == len(later) == len(paired) == 226
    records = []
    for r in older:
        key = r['period'], r['observation_id'], r['variant']
        alt = paired[key]; assert alt['new_status'] == 'verified'
        lev, decision, entry_ts, side = int(r['variant'].rsplit('_', 1)[1].rstrip('x')), int(r['decision_ts']), int(r['entry_ts']), int(r['side'])
        assert int(r['reference_ts']) >= decision + 1000 and entry_ts >= int(r['reference_ts']) + 1000
        entry = D(r['entry_fill'])
        assert abs(net(side, entry, D(r['exit_raw']), D(r['funding']), D('.0005')) - D(r['net'])) < D('1e-11')
        gates = {'base': True, 'distance': r['extension_gate'] == 'True', 'oi': r['oi_gate'] == 'True', 'oi_distance': r['both'] == 'True'}
        for holding, raw, funding in [('original', r['exit_raw'], r['funding']), ('extended', alt['new_exit_raw'], alt['new_funding'])]:
            records.append({'period': r['period'], 'observation_id': r['observation_id'], 'leverage': lev, 'holding_rule': holding,
                            'decision_ts': decision, 'quarter_start': decision // Q * Q, 'early': decision % Q < FIVE,
                            'entry_ts': entry_ts, 'side': side, 'entry_fill': entry, 'exit_raw': D(raw), 'funding': D(funding), **gates})
    ledger90 = pd.read_parquet(R90 / '一秒回放批次/动态池单位收益与风险.parquet')
    by90 = {(x['observation_id'], x['holding_rule'], x['variant']): x for x in ledger90.to_dict('records')}
    sig90 = pd.read_parquet(R90 / '一秒回放批次/动态池逐笔信号筛查.parquet').set_index('observation_id').to_dict('index')
    for r in wallet90.load_records():
        signal = sig90[r['observation_id']]
        z = by90[(r['observation_id'], r['period'], r['variant'])]
        decision = int(r['decision_ts']); assert decision // Q * Q == int(signal['quarter_start'])
        records.append({'period': '2022', 'observation_id': r['observation_id'], 'leverage': r['leverage'],
                        'holding_rule': r['period'], 'decision_ts': decision, 'quarter_start': int(signal['quarter_start']),
                        'early': decision % Q < FIVE, 'entry_ts': int(r['entry_ts']), 'side': int(r['side']),
                        'entry_fill': D(r['entry_fill']), 'exit_raw': D(str(z['exit_raw'])), 'funding': D(str(z['funding'])),
                        **{k: r[k] for k in COHORTS}})
    assert len({(x['period'], x['observation_id'], x['leverage'], x['holding_rule']) for x in records}) == len(records)
    quality90 = json.loads((R90 / '二零二二一秒回测汇总.json').read_text(encoding='utf-8'))
    quality86 = json.loads((R86 / '首秒距离跨期对照.json').read_text(encoding='utf-8'))
    cohort86 = {'base': 'base', 'distance': 'extension_gate', 'oi': 'oi_gate', 'oi_distance': 'both'}
    def unknown(period, holding, lev, cohort):
        if period == '2022':
            row = next(x for x in quality90['rows'] if x['holding_rule'] == holding and x['leverage'] == lev and x['cohort'] == cohort and x['exit_slippage_pct'] == .05)
        else:
            row = next(x for x in quality86['rows'] if x['period'] == period and x['leverage'] == lev and x['cohort'] == cohort86[cohort] and x['exit_slippage_pct'] == .05)
        return row['unknown_candidates']
    table = []
    for period in (*PERIODS, 'all'):
      for holding in ('original', 'extended'):
       for lev in (10, 20):
        for cohort in COHORTS:
         group = [r for r in records if (period == 'all' or r['period'] == period) and r['holding_rule'] == holding and r['leverage'] == lev and r[cohort]]
         uncertain = sum(unknown(p, holding, lev, cohort) for p in PERIODS) if period == 'all' else unknown(period, holding, lev, cohort)
         for timing in ('all', 'early', 'later'):
          selected = group if timing == 'all' else [r for r in group if r['early'] == (timing == 'early')]
          for slip in (D('.0005'), D('.00075'), D('.001')):
            table.append({'period': period, 'holding_rule': holding, 'leverage': lev, 'cohort': cohort, 'timing': timing,
                          'exit_slippage_pct': float(100 * slip), **metrics(selected, slip),
                          'unknown_candidates_conservative': uncertain})
    fields = ['period', 'observation_id', 'leverage', 'holding_rule', 'decision_ts', 'quarter_start', 'early', 'entry_ts', 'side',
              'entry_fill', 'exit_raw', 'funding', *COHORTS]
    detail_path = H / '前五分钟过滤逐笔.csv'
    with detail_path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(records)
    out = {'rows': table, 'detail_sha256': sha(detail_path), 'frozen_sha256': sha(H / '冻结时点.json'),
           'audit90_sha256': sha(R90 / '二零二二汇总独立核验.json'), 'audit86_sha256': sha(R86 / '首秒距离独立核验.json'),
           'audit88_sha256': sha(R88 / '延长持有配对独立核验.json'), 'code_sha256': sha(Path(__file__)),
           'unknown_2022_rank_hours': 240, 'note': 'Frozen exploratory timing gate; 2022 later-selected universe and uncertain prior exposure prevent true blindness.'}
    (H / '前五分钟过滤对照.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT91_EVALUATED', len(records), 'paths', len(table), 'groups', flush=True)


if __name__ == '__main__':
    main()
