"""Run conditional known-path shared-wallet scenarios using the existing risk budget."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import replay_2022 as runner

H = Path(__file__).resolve().parent
R85 = H.parent / '第八十五轮_共享资金条件模拟'
sys.path.insert(0, str(R85))
from wallet_simulator import simulate


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def load_records():
    detail = pd.read_csv(H / '二零二二候选状态及单位账本.csv', dtype=str, keep_default_na=False)
    state = {(r['observation_id'], r['holding_rule'], int(r['leverage']), r['cohort']): r['category']
             for r in detail.to_dict('records')}
    signals = pd.read_parquet(H / '一秒回放批次/动态池逐笔信号筛查.parquet').set_index('observation_id').to_dict('index')
    ledger = pd.read_parquet(H / '一秒回放批次/动态池单位收益与风险.parquet')
    records = []
    for r in ledger.to_dict('records'):
        obs, period = r['observation_id'], r['holding_rule']
        lev = int(r['variant'].rsplit('_', 1)[1].rstrip('x'))
        if state[(obs, period, lev, 'base')] != 'trade': continue
        s = signals[obs]
        assert r['status'] == r['risk_status'] == 'verified' and not r['liq_proxy']
        assert s['status'] == 'qualified' and s[f'precheck_{lev}x'] == 'passed'
        assert int(s['entry_exec_ts']) == int(r['entry_signal_reference_ts'])
        funding = json.loads(r['funding_events_json'])
        assert abs(sum(float(x['charge']) for x in funding) - float(r['funding'])) < 1e-11
        records.append({'period': period, 'observation_id': obs, 'variant': r['variant'], 'leverage': lev,
                        **{cohort: state[(obs, period, lev, cohort)] == 'trade' for cohort in ('base', 'distance', 'oi', 'oi_distance')},
                        'side': int(r['side']), 'decision_ts': int(r['decision_ts']),
                        'reference_ts': int(s['entry_exec_ts']), 'reference': str(s['raw_entry_1s']), 'stop': str(s['stop_price']),
                        'entry_ts': int(r['entry_ts']), 'entry_fill': str(r['entry_fill']),
                        'exit_signal_ts': int(r['exit_signal_ts']), 'exit_ts': int(r['exit_ts']),
                        'exit_fill': str(r['exit_fill']), 'unit_net': str(r['net_per_unit_notional']),
                        'funding_events': funding})
    assert len({(x['period'], x['observation_id'], x['leverage']) for x in records}) == len(records)
    return records


def main():
    runner.guard(start=True)
    audit = json.loads((H / '二零二二汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['report_sha256'] == sha(H / '二零二二一秒回测汇总.json')
    assert audit['detail_sha256'] == sha(H / '二零二二候选状态及单位账本.csv')
    test = json.loads((R85 / '钱包时序合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(R85 / 'wallet_simulator.py')
    records = load_records()
    summaries, outcomes, journals = [], [], []
    for cohort in ('base', 'distance', 'oi', 'oi_distance'):
      for lev in (10, 20):
       for period in ('original', 'extended'):
        selected = [r for r in records if r['leverage'] == lev and r['period'] == period and r[cohort]]
        for reverse in (False, True):
            summary, rows, journal = simulate(selected, lev, reverse_ties=reverse)
            extra = {'cohort': cohort, 'leverage': lev, 'period': period, 'reverse_ties': reverse}
            summaries.append({**extra, **{k: float(v) if isinstance(v, Decimal) else v for k, v in summary.items()}})
            for obs, value in rows.items():
                outcomes.append({**extra, 'observation_id': obs, 'source_period': period,
                                 **{k: value.get(k) for k in ('status', 'quantity', 'net_pnl', 'planned_risk', 'reference_wallet',
                                                              'estimated_entry', 'margin', 'open_fee', 'funding_paid')}})
            journals.extend({**extra, **j} for j in journal)
    def write(path, data):
        assert data
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0])); writer.writeheader(); writer.writerows(data)
    write(H / '共享钱包情景逐笔.csv', outcomes)
    write(H / '共享钱包事件账本.csv', journals)
    out = {'rows': summaries, 'outcomes_sha256': sha(H / '共享钱包情景逐笔.csv'),
           'journal_sha256': sha(H / '共享钱包事件账本.csv'), 'frozen_sha256': sha(H / '冻结时点.json'),
           'test_sha256': sha(R85 / '钱包时序合成核验.json'), 'engine_sha256': sha(R85 / 'wallet_simulator.py'),
           'code_sha256': sha(Path(__file__)), 'unknown_rank_hours': 240,
           'note': 'Conditional known paths only; unknown opportunities omitted and floating drawdown is unavailable.'}
    (H / '共享钱包情景汇总.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT90_WALLET', json.dumps([x for x in summaries if x['leverage'] == 20 and not x['reverse_ties']], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
