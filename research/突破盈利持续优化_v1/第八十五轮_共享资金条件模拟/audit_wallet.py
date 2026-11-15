"""Independent event-by-event wallet, risk budget and summary reconstruction."""
import csv
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
R81 = P / '第八十一轮_八至十月一秒观察'
R82 = P / '第八十二轮_八至十月持仓量过滤'
D = Decimal
PERIODS = ('2023', '2024', '2026', '2026_aug_oct')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return abs(D(str(a)) - D(str(b))) < D('0.00000001')


def load_inputs(frozen):
    r79 = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    with (R82 / '四时段持仓量已核验逐笔.csv').open(encoding='utf-8', newline='') as f:
        gates = {(x['period'], x['observation_id'], x['variant']) for x in csv.DictReader(f)}
    data = []
    for period in PERIODS:
        if period == '2026_aug_oct':
            root = R81 / '冻结结果'
            manifest = root / '冻结哈希.json'
            assert sha(manifest) == frozen['sources_sha256']['r81_complete_snapshot']
        else:
            root = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            manifest = root / '完整快照哈希.json'
            assert sha(manifest) == r79['base_snapshots'][period]
        m = json.loads(manifest.read_text(encoding='utf-8'))
        sp, lp = 'batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet'
        assert sha(root / sp) == m['files'][sp] and sha(root / lp) == m['files'][lp]
        signals = {x['observation_id']: x for x in pq.read_table(root / sp).to_pylist()}
        for r in pq.read_table(root / lp).to_pylist():
            if not (r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False):
                continue
            s = signals[r['observation_id']]
            lev = int(r['variant'].rsplit('_', 1)[1].rstrip('x'))
            assert s['status'] == 'qualified' and s[f'precheck_{lev}x'] == 'passed'
            assert s['entry_exec_ts'] == r['entry_signal_reference_ts'] and s['decision_ts'] == r['decision_ts']
            data.append({'period': period, 'obs': r['observation_id'], 'lev': lev,
                         'oi': (period, r['observation_id'], r['variant']) in gates,
                         'side': int(r['side']), 'reference_ts': int(s['entry_exec_ts']), 'reference': D(str(s['raw_entry_1s'])),
                         'stop': D(str(s['stop_price'])), 'entry_ts': int(r['entry_ts']), 'entry': D(str(r['entry_fill'])),
                         'exit_ts': int(r['exit_ts']), 'exit': D(str(r['exit_fill'])), 'unit_net': D(str(r['net_per_unit_notional'])),
                         'funding': json.loads(r['funding_events_json'])})
    assert len(data) == 226 and sum(x['oi'] for x in data) == 70
    return data


def main():
    summary_path = H / '共享钱包情景汇总.json'
    result = json.loads(summary_path.read_text(encoding='utf-8'))
    assert result['frozen_sha256'] == sha(H / '冻结时点.json') and result['code_sha256'] == sha(H / 'run_wallet.py')
    assert result['engine_sha256'] == sha(H / 'wallet_simulator.py') and result['test_sha256'] == sha(H / '钱包时序合成核验.json')
    assert result['outcomes_sha256'] == sha(H / '共享钱包情景逐笔.csv') and result['journal_sha256'] == sha(H / '共享钱包事件账本.csv')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for key, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['sources_sha256'][key]
    data = load_inputs(frozen)
    with (H / '共享钱包情景逐笔.csv').open(encoding='utf-8', newline='') as f:
        outcome_rows = list(csv.DictReader(f))
    with (H / '共享钱包事件账本.csv').open(encoding='utf-8', newline='') as f:
        journal_rows = list(csv.DictReader(f))
    assert len(result['rows']) == 40
    count_events = count_outcomes = 0
    with localcontext() as ctx:
        ctx.prec = 42
        for out in result['rows']:
            cohort, lev, period, reverse = out['cohort'], int(out['leverage']), out['period'], bool(out['reverse_ties'])
            selected = [r for r in data if r['lev'] == lev and (cohort == 'base' or r['oi']) and (period == 'linked' or r['period'] == period)]
            actual_outcomes = {r['observation_id']: r for r in outcome_rows if r['cohort'] == cohort and int(r['leverage']) == lev and r['period'] == period and (r['reverse_ties'] == str(reverse))}
            journal = [r for r in journal_rows if r['cohort'] == cohort and int(r['leverage']) == lev and r['period'] == period and (r['reverse_ties'] == str(reverse))]
            assert len(selected) == len(actual_outcomes) == out['known_opportunities']
            order = {obs: i for i, obs in enumerate(sorted((r['obs'] for r in selected), reverse=reverse))}
            times = []
            for r in selected:
                times.append((r['reference_ts'], 0, order[r['obs']], 0, 'reference', r, None))
                times.append((r['entry_ts'], 1, order[r['obs']], 0, 'entry', r, None))
                for i, charge in enumerate(r['funding']):
                    times.append((int(charge['settlement_ts']), 2, order[r['obs']], i, 'funding', r, charge))
                times.append((r['exit_ts'], 3, order[r['obs']], 0, 'exit', r, None))
            times.sort(key=lambda x: x[:4])
            wallet, lock, peak, drawdown, max_active = D(1000), D(0), D(1000), D(0), 0
            pending, active, completed = {}, {}, []
            j = 0

            def snapshot(ts, typ, obs, status):
                nonlocal j, peak, drawdown, max_active
                peak = max(peak, wallet)
                drawdown = max(drawdown, (peak - wallet) / peak)
                max_active = max(max_active, len(active))
                assert j < len(journal)
                got = journal[j]; j += 1
                assert (int(got['ts']), got['event'], got['observation_id'], got['status']) == (ts, typ, obs, status)
                assert near(got['wallet'], wallet) and near(got['locked_margin'], lock)
                assert near(got['pending_reserve'], sum((x['reserve'] for x in pending.values()), D(0)))
                assert near(got['planned_open_risk'], sum((x['risk'] for x in [*pending.values(), *active.values()]), D(0)))

            for ts, _, _, _, typ, r, charge in times:
                obs = r['obs']
                got = actual_outcomes[obs]
                if typ == 'reference':
                    side = D(r['side'])
                    expected_entry = r['reference'] * (1 + side * D('.0005'))
                    expected_stop = r['stop'] * (1 - side * D('.0005'))
                    risk_unit = side * (expected_entry - expected_stop) + D('.0005') * (expected_entry + expected_stop)
                    available = max(D(0), wallet - lock - sum((x['reserve'] for x in pending.values()), D(0)))
                    used_risk = sum((x['risk'] for x in [*pending.values(), *active.values()]), D(0))
                    budget = max(D(0), min(wallet * D('.005'), wallet * D('.01') - used_risk))
                    margin_unit = expected_entry / D(lev) + expected_entry * D('.0005')
                    qty = D(0) if budget <= abs(wallet) * D('1e-18') or available <= abs(wallet) * D('1e-18') else min(budget / risk_unit, available / margin_unit)
                    if qty <= 0:
                        assert got['status'] == 'signal_rejected_budget_or_funds' and near(got['net_pnl'], 0)
                        snapshot(ts, typ, obs, 'signal_rejected_budget_or_funds')
                        continue
                    pending[obs] = {'qty': qty, 'reserve': qty * margin_unit, 'risk': qty * risk_unit}
                    assert near(got['quantity'], qty) and near(got['planned_risk'], qty * risk_unit)
                    assert near(got['reference_wallet'], wallet) and near(got['estimated_entry'], expected_entry)
                    snapshot(ts, typ, obs, 'reserved')
                elif typ == 'entry':
                    if obs not in pending:
                        continue
                    order_ = pending.pop(obs)
                    margin = order_['qty'] * r['entry'] / D(lev)
                    fee = order_['qty'] * r['entry'] * D('.0005')
                    available = wallet - lock - sum((x['reserve'] for x in pending.values()), D(0))
                    if margin + fee > available + D('1e-25'):
                        assert got['status'] == 'entry_rejected_insufficient_margin' and near(got['net_pnl'], 0)
                        snapshot(ts, typ, obs, 'entry_rejected_insufficient_margin')
                        continue
                    wallet -= fee
                    lock += margin
                    active[obs] = {**order_, 'margin': margin, 'fee': fee, 'funding': D(0)}
                    assert near(got['margin'], margin) and near(got['open_fee'], fee)
                    snapshot(ts, typ, obs, 'filled')
                elif typ == 'funding':
                    if obs not in active:
                        continue
                    value = active[obs]['qty'] * r['entry'] * D(str(charge['charge']))
                    wallet -= value
                    active[obs]['funding'] += value
                    snapshot(ts, typ, obs, 'funding_applied')
                else:
                    if obs not in active:
                        continue
                    position = active.pop(obs)
                    closing = position['qty'] * (D(r['side']) * (r['exit'] - r['entry']) - D('.0005') * r['exit'])
                    wallet += closing
                    lock -= position['margin']
                    pnl = closing - position['fee'] - position['funding']
                    assert got['status'] == 'closed' and near(got['net_pnl'], pnl)
                    assert near(pnl, position['qty'] * r['entry'] * r['unit_net'])
                    completed.append(pnl)
                    snapshot(ts, typ, obs, 'closed')
            assert j == len(journal) and not pending and not active and near(lock, 0)
            assert out['simulated_trades'] == len(completed) and out['net_wins'] == sum(x > 0 for x in completed)
            assert out['rejected_signals'] == len(selected) - len(completed) and out['maximum_open_positions'] == max_active
            assert near(out['final_wallet'], wallet) and near(out['net_pnl'], wallet - D(1000))
            assert near(out['net_return_pct'], (wallet / D(1000) - 1) * 100)
            assert near(out['realized_wallet_drawdown_pct'], drawdown * 100)
            assert near(wallet - D(1000), sum(completed, D(0)))
            if completed:
                assert near(out['net_win_rate_pct'], D(100) * sum(x > 0 for x in completed) / len(completed))
                neg = -sum((x for x in completed if x < 0), D(0))
                pos = sum((x for x in completed if x > 0), D(0))
                assert out['profit_factor'] is None if neg == 0 else near(out['profit_factor'], pos / neg)
            count_events += j
            count_outcomes += len(actual_outcomes)
    audit = {'all_checks_pass': True, 'scenarios_checked': len(result['rows']), 'trade_outcome_rows_checked': count_outcomes,
             'wallet_events_checked': count_events, 'result_sha256': sha(summary_path), 'code_sha256': sha(Path(__file__)),
             'note': 'Cash, planned risk and fees checked; unknown candidates omitted and floating drawdown not simulated.'}
    (H / '共享钱包独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT85_WALLET_AUDIT', json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
