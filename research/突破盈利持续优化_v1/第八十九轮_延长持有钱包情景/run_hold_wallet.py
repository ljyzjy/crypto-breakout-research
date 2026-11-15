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
R88 = P / '第八十八轮_延长一根柱持有'
sys.path.insert(0, str(R85))
from wallet_simulator import simulate
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][name]
    test = json.loads((R85 / '钱包时序合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(R85 / 'wallet_simulator.py')
    with (R86 / '首秒距离逐笔.csv').open(encoding='utf-8', newline='') as f:
        gates = {(r['period'], r['observation_id'], r['variant']): r for r in csv.DictReader(f)}
    changed = json.loads((R88 / '延长持有风险账本.json').read_text(encoding='utf-8'))
    extended = {(r['period'], r['observation_id'], r['variant']): r for r in changed['records']}
    assert len(extended) == 68 and not changed['unknown']
    original = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    records = []
    for period in PERIODS:
        if period == '2026_aug_oct':
            root = R81 / '冻结结果'; manifest = root / '冻结哈希.json'
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
            key = period, r['observation_id'], r['variant']
            s, g = signals[r['observation_id']], gates[key]
            lev = int(r['variant'].rsplit('_', 1)[1].rstrip('x'))
            assert s['status'] == 'qualified' and s[f'precheck_{lev}x'] == 'passed'
            assert s['entry_exec_ts'] == r['entry_signal_reference_ts'] and s['decision_ts'] == r['decision_ts']
            if key in extended:
                pair = extended[key]
                assert pair['extended']['status'] == pair['risk']['risk_status'] == 'verified' and not pair['risk']['liq_proxy']
                assert pair['extended']['entry_ts'] == r['entry_ts'] and abs(pair['extended']['entry_fill'] - r['entry_fill']) < 1e-9
                path, risk = pair['extended'], pair['risk']
            else:
                assert r['reason'] != 'quarter_time'
                path, risk = r, r
            funds = json.loads(risk['funding_events_json'])
            assert abs(sum(float(x['charge']) for x in funds) - float(risk['funding'])) < 1e-11
            records.append({'period': period, 'observation_id': r['observation_id'], 'variant': r['variant'], 'leverage': lev,
                            'base': True, 'extension_gate': g['extension_gate'] == 'True', 'oi_gate': g['oi_gate'] == 'True',
                            'both': g['both'] == 'True', 'side': int(r['side']), 'decision_ts': int(r['decision_ts']),
                            'reference_ts': int(s['entry_exec_ts']), 'reference': str(s['raw_entry_1s']), 'stop': str(s['stop_price']),
                            'entry_ts': int(path['entry_ts']), 'entry_fill': str(path['entry_fill']), 'exit_signal_ts': int(path['exit_signal_ts']),
                            'exit_ts': int(path['exit_ts']), 'exit_fill': str(path['exit_fill']), 'unit_net': str(risk['net_per_unit_notional']),
                            'funding_events': funds})
    assert len(records) == len(gates) == 226
    prior = json.loads((R88 / '延长持有配对汇总.json').read_text(encoding='utf-8'))
    summaries, outcomes, journals = [], [], []
    for cohort in ('base', 'extension_gate', 'oi_gate', 'both'):
        for lev in (10, 20):
            universe = [r for r in records if r['leverage'] == lev and r[cohort]]
            for period in (*PERIODS, 'linked'):
                selected = universe if period == 'linked' else [r for r in universe if r['period'] == period]
                previous_period = 'all' if period == 'linked' else period
                expected = next(x for x in prior['rows'] if x['period'] == previous_period and x['leverage'] == lev and x['cohort'] == cohort and x['comparison'] == 'extended' and x['exit_slippage_pct'] == .05)
                assert len(selected) == expected['known_trades']
                lookup = {r['observation_id']: r for r in selected}
                for reverse in (False, True):
                    result, rows, journal = simulate(selected, lev, reverse_ties=reverse)
                    extra = {'cohort': cohort, 'leverage': lev, 'period': period, 'reverse_ties': reverse}
                    summaries.append({**extra, **{k: float(v) if isinstance(v, Decimal) else v for k, v in result.items()}})
                    for obs, data in rows.items():
                        outcomes.append({**extra, 'observation_id': obs, 'source_period': lookup[obs]['period'],
                                         **{k: data.get(k) for k in ('status', 'quantity', 'net_pnl', 'planned_risk', 'reference_wallet', 'estimated_entry', 'margin', 'open_fee', 'funding_paid')}})
                    journals.extend({**extra, **j} for j in journal)
    def write(path, rows):
        assert rows
        with path.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    write(H / '延长钱包情景逐笔.csv', outcomes)
    write(H / '延长钱包事件账本.csv', journals)
    out = {'rows': summaries, 'outcomes_sha256': sha(H / '延长钱包情景逐笔.csv'), 'journal_sha256': sha(H / '延长钱包事件账本.csv'),
           'frozen_sha256': sha(H / '冻结时点.json'), 'test_sha256': sha(R85 / '钱包时序合成核验.json'),
           'engine_sha256': sha(R85 / 'wallet_simulator.py'), 'code_sha256': sha(Path(__file__)), 'unknown_original_candidates': 42,
           'note': 'Conditional known paths; unknown trades omitted; realized wallet drawdown excludes floating PnL.'}
    (H / '延长钱包情景汇总.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in summaries:
        if r['period'] == 'linked' and not r['reverse_ties']:
            print('EXT89_LINKED', json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
