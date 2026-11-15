"""Run frozen known-only wallet scenarios; no real orders or live assets."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from wallet_simulator import simulate

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
R82 = P / '第八十二轮_八至十月持仓量过滤'
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    f = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert f['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, path in f['source_paths'].items():
        assert sha(Path(path)) == f['sources_sha256'][name]
    test = json.loads((H / '钱包时序合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(H / 'wallet_simulator.py')
    assert test['test_code_sha256'] == sha(H / 'test_wallet_simulator.py')
    frozen = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    with (R82 / '四时段持仓量已核验逐笔.csv').open(encoding='utf-8', newline='') as fcsv:
        oi_keys = {(x['period'], x['observation_id'], x['variant']) for x in csv.DictReader(fcsv)}
    assert len(oi_keys) == 70
    records = []
    for period in PERIODS:
        if period == '2026_aug_oct':
            root = R81 / '冻结结果'
            manifest_path = root / '冻结哈希.json'
            assert sha(manifest_path) == f['sources_sha256']['r81_complete_snapshot']
        else:
            root = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            manifest_path = root / '完整快照哈希.json'
            assert sha(manifest_path) == frozen['base_snapshots'][period]
        m = json.loads(manifest_path.read_text(encoding='utf-8'))
        assert m['all_checks_pass']
        names = ['batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet']
        for name in names:
            assert sha(root / name) == m['files'][name]
        signals = {x['observation_id']: x for x in pq.read_table(root / names[0]).to_pylist()}
        paths = pq.read_table(root / names[1]).to_pylist()
        for row in paths:
            if row['status'] != 'verified' or row['risk_status'] != 'verified' or row['liq_proxy'] is not False:
                continue
            obs, var = row['observation_id'], row['variant']
            s = signals[obs]
            lev = int(var.rsplit('_', 1)[1].rstrip('x'))
            assert s['status'] == 'qualified' and s[f'precheck_{lev}x'] == 'passed'
            assert int(s['side']) == int(row['side']) and int(s['decision_ts']) == int(row['decision_ts'])
            assert int(s['entry_exec_ts']) == int(row['entry_signal_reference_ts'])
            assert abs(float(s['stop_price']) - float(row['initial_stop'])) < 1e-9
            funding = json.loads(row['funding_events_json'])
            assert abs(sum(float(x['charge']) for x in funding) - float(row['funding'])) < 1e-11
            records.append({'period': period, 'observation_id': obs, 'variant': var, 'leverage': lev,
                            'oi_gate': (period, obs, var) in oi_keys, 'side': int(row['side']),
                            'decision_ts': int(row['decision_ts']), 'reference_ts': int(s['entry_exec_ts']),
                            'reference': str(s['raw_entry_1s']), 'stop': str(s['stop_price']),
                            'entry_ts': int(row['entry_ts']), 'entry_fill': str(row['entry_fill']),
                            'exit_signal_ts': int(row['exit_signal_ts']), 'exit_ts': int(row['exit_ts']),
                            'exit_fill': str(row['exit_fill']), 'unit_net': str(row['net_per_unit_notional']),
                            'funding_events': funding})
    assert len(records) == 226 and len({(r['period'], r['observation_id'], r['variant']) for r in records}) == len(records)
    assert sum(r['oi_gate'] for r in records) == 70
    outcomes_rows, journals, summaries = [], [], []
    for cohort in ('base', 'oi_gate'):
        for lev in (10, 20):
            universe = [r for r in records if r['leverage'] == lev and (cohort == 'base' or r['oi_gate'])]
            for period in (*PERIODS, 'linked'):
                selected = universe if period == 'linked' else [r for r in universe if r['period'] == period]
                by_obs = {r['observation_id']: r for r in selected}
                for reverse in (False, True):
                    summary, outcomes, journal = simulate(selected, lev, reverse_ties=reverse)
                    extra = {'cohort': cohort, 'leverage': lev, 'period': period, 'reverse_ties': reverse}
                    summaries.append({**extra, **{k: (float(v) if isinstance(v, Decimal) else v) for k, v in summary.items()}})
                    for obs, value in outcomes.items():
                        row = {'cohort': cohort, 'leverage': lev, 'period': period, 'reverse_ties': reverse,
                               'observation_id': obs, 'source_period': by_obs[obs]['period'],
                               **{k: value.get(k) for k in ('status', 'quantity', 'net_pnl', 'planned_risk', 'reference_wallet', 'estimated_entry', 'margin', 'open_fee', 'funding_paid')}}
                        outcomes_rows.append(row)
                    journals.extend({**extra, **j} for j in journal)
    def write(path, data):
        if not data:
            raise AssertionError('empty_output')
        with path.open('w', encoding='utf-8', newline='') as file:
            w = csv.DictWriter(file, fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
    write(H / '共享钱包情景逐笔.csv', outcomes_rows)
    write(H / '共享钱包事件账本.csv', journals)
    out = {'rows': summaries, 'outcomes_sha256': sha(H / '共享钱包情景逐笔.csv'),
           'journal_sha256': sha(H / '共享钱包事件账本.csv'), 'frozen_sha256': sha(H / '冻结时点.json'),
           'test_sha256': sha(H / '钱包时序合成核验.json'), 'engine_sha256': sha(H / 'wallet_simulator.py'),
           'code_sha256': sha(Path(__file__)), 'unknown_original_candidates': 42,
           'note': 'Known-path conditional wallet only; unknown opportunities omitted, no floating-PnL drawdown or real fills.'}
    (H / '共享钱包情景汇总.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in summaries:
        if r['period'] == 'linked' and not r['reverse_ties']:
            print('EXT85_LINKED', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
