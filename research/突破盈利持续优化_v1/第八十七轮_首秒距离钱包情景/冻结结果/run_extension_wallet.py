import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
R85 = P / '第八十五轮_共享资金条件模拟'
R86 = P / '第八十六轮_首秒追价距离过滤'
sys.path.insert(0, str(R85))
from wallet_simulator import simulate

PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for key, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][key]
    test = json.loads((R85 / '钱包时序合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(R85 / 'wallet_simulator.py')
    with (R86 / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f:
        gate = {(r['period'], r['observation_id'], r['variant']): r for r in csv.DictReader(f)}
    original = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    records = []
    for period in PERIODS:
        if period == '2026_aug_oct':
            root = R81 / '冻结结果'
            manifest = root / '冻结哈希.json'
            assert sha(manifest) == frozen['sources_sha256']['r81_complete_snapshot']
        else:
            root = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            manifest = root / '完整快照哈希.json'
            assert sha(manifest) == original['base_snapshots'][period]
        m = json.loads(manifest.read_text(encoding='utf-8'))
        sn, pn = 'batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet'
        assert sha(root / sn) == m['files'][sn] and sha(root / pn) == m['files'][pn]
        signals = {r['observation_id']: r for r in pq.read_table(root / sn).to_pylist()}
        for r in pq.read_table(root / pn).to_pylist():
            if not (r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False):
                continue
            s = signals[r['observation_id']]
            key = period, r['observation_id'], r['variant']
            row = gate[key]
            assert row['extension_gate'] in ('True', 'False', '') and row['both'] in ('True', 'False', '')
            lev = int(r['variant'].rsplit('_', 1)[1].rstrip('x'))
            assert s['status'] == 'qualified' and s[f'precheck_{lev}x'] == 'passed'
            assert s['decision_ts'] == r['decision_ts'] and s['entry_exec_ts'] == r['entry_signal_reference_ts']
            funding = json.loads(r['funding_events_json'])
            assert abs(sum(float(x['charge']) for x in funding) - float(r['funding'])) < 1e-11
            records.append({'period': period, 'observation_id': r['observation_id'], 'variant': r['variant'],
                            'leverage': lev, 'extension_gate': row['extension_gate'] == 'True', 'both': row['both'] == 'True',
                            'side': int(r['side']), 'decision_ts': int(r['decision_ts']), 'reference_ts': int(s['entry_exec_ts']),
                            'reference': str(s['raw_entry_1s']), 'stop': str(s['stop_price']), 'entry_ts': int(r['entry_ts']),
                            'entry_fill': str(r['entry_fill']), 'exit_signal_ts': int(r['exit_signal_ts']), 'exit_ts': int(r['exit_ts']),
                            'exit_fill': str(r['exit_fill']), 'unit_net': str(r['net_per_unit_notional']), 'funding_events': funding})
    assert len(records) == len(gate) == 226
    prior = json.loads((R86 / '首秒距离跨期对照.json').read_text(encoding='utf-8'))
    summaries, outcomes, journal = [], [], []
    for cohort in ('extension_gate', 'both'):
        for lev in (10, 20):
            universe = [r for r in records if r['leverage'] == lev and r[cohort]]
            for period in (*PERIODS, 'linked'):
                selected = universe if period == 'linked' else [r for r in universe if r['period'] == period]
                expected_period = 'all' if period == 'linked' else period
                expected = next(x for x in prior['rows'] if x['period'] == expected_period and x['leverage'] == lev and x['cohort'] == cohort and x['exit_slippage_pct'] == .05)
                assert len(selected) == expected['known_trades']
                by_obs = {r['observation_id']: r for r in selected}
                for reverse in (False, True):
                    summary, results, events = simulate(selected, lev, reverse_ties=reverse)
                    extra = {'cohort': cohort, 'leverage': lev, 'period': period, 'reverse_ties': reverse}
                    summaries.append({**extra, **{k: float(v) if isinstance(v, Decimal) else v for k, v in summary.items()}})
                    for obs, data in results.items():
                        outcomes.append({**extra, 'observation_id': obs, 'source_period': by_obs[obs]['period'],
                                         **{k: data.get(k) for k in ('status', 'quantity', 'net_pnl', 'planned_risk', 'reference_wallet', 'estimated_entry', 'margin', 'open_fee', 'funding_paid')}})
                    journal.extend({**extra, **e} for e in events)
    def write(path, rows):
        assert rows
        with path.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    write(H / '首秒距离钱包情景逐笔.csv', outcomes)
    write(H / '首秒距离钱包事件账本.csv', journal)
    out = {'rows': summaries, 'outcomes_sha256': sha(H / '首秒距离钱包情景逐笔.csv'),
           'journal_sha256': sha(H / '首秒距离钱包事件账本.csv'), 'frozen_sha256': sha(H / '冻结时点.json'),
           'test_sha256': sha(R85 / '钱包时序合成核验.json'), 'engine_sha256': sha(R85 / 'wallet_simulator.py'),
           'code_sha256': sha(Path(__file__)), 'unknown_original_candidates': 42,
           'note': 'Known paths only; unknown candidates omitted; wallet drawdown does not include floating PnL.'}
    (H / '首秒距离钱包情景汇总.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in summaries:
        if r['period'] == 'linked' and not r['reverse_ties']:
            print('EXT87_LINKED', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
