"""Account for each frozen candidate and score only risk-verified paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import replay_2022 as runner

H = Path(__file__).resolve().parent
P = H.parent
B = H / '一秒回放批次'
sys.path.insert(0, str(P / '第八十六轮_首秒追价距离过滤'))
from extension_gate import gate as distance_gate
D = Decimal
getcontext().prec = 40
BENIGN = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def metrics(trades):
    net = [r['net'] for r in trades]
    wins, losses = [x for x in net if x > 0], [x for x in net if x < 0]
    days = {pd.Timestamp(int(x['entry_ts']), unit='ms', tz='UTC').strftime('%Y-%m-%d') for x in trades}
    return {'trades': len(net), 'net_wins': len(wins), 'net_win_rate_pct': float(D(100) * len(wins) / len(net)) if net else None,
            'average_net_pct_notional': float(D(100) * sum(net) / len(net)) if net else None,
            'profit_factor': float(sum(wins) / -sum(losses)) if losses else None, 'active_utc_days': len(days)}


def main():
    runner.guard(start=True)
    tape_audit = json.loads((H / '一秒逐笔独立样本核验.json').read_text(encoding='utf-8'))
    risk_audit = json.loads((H / '风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    oi_audit = json.loads((H / '持仓量逐点独立核验.json').read_text(encoding='utf-8'))
    assert tape_audit['all_checks_pass'] and tape_audit['batch_fingerprint'] == runner.fingerprint()
    assert tape_audit['code_sha256'] == sha(H / 'audit_tapes_2022.py')
    assert risk_audit['all_checks_pass'] and risk_audit['code_sha256'] == sha(H / 'audit_risk_2022.py')
    assert oi_audit['all_checks_pass'] and oi_audit['code_sha256'] == sha(H / 'audit_oi_2022.py')
    assert oi_audit['source_sha256'] == sha(H / '持仓量逐点来源核验.json')
    ledger_path = B / '动态池单位收益与风险.parquet'
    assert risk_audit['ledger_sha256'] == sha(ledger_path)
    sig, paths, ledger = (pd.read_parquet(B / name) for name in
        ('动态池逐笔信号筛查.parquet', '动态池延迟市价路径.parquet', '动态池单位收益与风险.parquet'))
    assert len(sig) == 310 and sig.observation_id.is_unique
    path_by = {(r['observation_id'], r['holding_rule'], r['variant']): r for r in paths.to_dict('records')}
    ledger_by = {(r['observation_id'], r['holding_rule'], r['variant']): r for r in ledger.to_dict('records')}
    assert len(path_by) == len(paths) and len(ledger_by) == len(ledger)
    oi = json.loads((H / '持仓量逐点来源核验.json').read_text(encoding='utf-8'))
    events = {x['observation_id']: x for x in oi['events']}
    points = {(x['symbol'], int(x['ts'])): x for x in oi['points']}
    def oi_gate(obs):
        e = events.get(obs)
        if not e: return None
        values = {}
        for sym in ('BTCUSDT', 'ETHUSDT'):
            for k in ('oi_t0', 'oi_previous'):
                p = points.get((sym, int(e[k])))
                if not p or p['status'] != 'verified': return None
                assert len(p['official_values']) == 1
                values[(sym, k)] = D(p['official_values'][0])
        return all(values[(sym, 'oi_t0')] > values[(sym, 'oi_previous')] for sym in ('BTCUSDT', 'ETHUSDT'))
    detail, summary = [], []
    for holding in ('original', 'extended'):
      for lev in (10, 20):
       variant = f'one_observation_2r_{lev}x'
       for cohort, use_distance, use_oi in [('base', False, False), ('distance', True, False),
                                             ('oi', False, True), ('oi_distance', True, True)]:
        trades, unknown, no_order = [], 0, 0
        for s in sig.to_dict('records'):
            key = (s['observation_id'], holding, variant)
            item = {'observation_id': s['observation_id'], 'holding_rule': holding, 'leverage': lev,
                    'cohort': cohort, 'signal_status': s['status'], 'category': '', 'reason': ''}
            if s['status'] not in BENIGN:
                item.update(category='unknown', reason=s['status']); unknown += 1
            elif s['status'] != 'qualified':
                item.update(category='no_order', reason=s['status']); no_order += 1
            elif pd.isna(s[f'precheck_{lev}x']):
                item.update(category='unknown', reason='missing_precheck'); unknown += 1
            elif s[f'precheck_{lev}x'] != 'passed':
                item.update(category='no_order', reason=s[f'precheck_{lev}x']); no_order += 1
            elif key not in path_by or path_by[key]['status'] != 'verified':
                item.update(category='unknown', reason='missing_or_unverified_path'); unknown += 1
            elif key not in ledger_by or ledger_by[key]['risk_status'] != 'verified':
                item.update(category='unknown', reason='missing_or_unverified_risk'); unknown += 1
            elif bool(ledger_by[key]['liq_proxy']):
                item.update(category='unknown', reason='liquidation_proxy'); unknown += 1
            else:
                distance, _ = distance_gate(s)
                oi_pass = oi_gate(s['observation_id']) if use_oi else True
                if use_distance and distance is None or use_oi and oi_pass is None:
                    item.update(category='unknown', reason='filter_source_unknown'); unknown += 1
                elif use_distance and not distance or use_oi and not oi_pass:
                    item.update(category='no_order', reason='fixed_filter_rejected'); no_order += 1
                else:
                    r = ledger_by[key]
                    side, fill, raw, funding = int(r['side']), D(str(r['entry_fill'])), D(str(r['exit_raw'])), D(str(r['funding']))
                    assert int(r['entry_signal_reference_ts']) >= int(r['decision_ts']) + 1000
                    assert int(r['entry_ts']) >= int(r['entry_signal_reference_ts']) + 1000
                    assert int(r['exit_ts']) >= int(r['exit_signal_ts']) + 5000
                    exit_fill = raw * (1 - D(side) * D('.0005'))
                    net = D(side) * (exit_fill - fill) / fill - D('.0005') - D('.0005') * exit_fill / fill - funding
                    assert abs(net - D(str(r['net_per_unit_notional']))) < D('1e-11')
                    trade = {'entry_ts': int(r['entry_ts']), 'entry_fill': fill, 'exit_raw': raw, 'side': side,
                             'funding': funding, 'net': net}
                    trades.append(trade)
                    item.update(category='trade', reason=r['reason'], **trade)
            detail.append(item)
        assert len(trades) + unknown + no_order == len(sig)
        for slip in (D('.0005'), D('.00075'), D('.001')):
            stress = []
            for r in trades:
                ex = r['exit_raw'] * (1 - D(r['side']) * slip)
                value = D(r['side']) * (ex - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * ex / r['entry_fill'] - r['funding']
                stress.append({**r, 'net': value})
            summary.append({'holding_rule': holding, 'leverage': lev, 'cohort': cohort, 'exit_slippage_pct': float(D(100) * slip),
                            **metrics(stress), 'known_no_order': no_order, 'unknown_candidates': unknown, 'candidate_events': len(sig)})
    columns = ['observation_id', 'holding_rule', 'leverage', 'cohort', 'signal_status', 'category', 'reason',
               'entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding', 'net']
    path = H / '二零二二候选状态及单位账本.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns); writer.writeheader(); writer.writerows(detail)
    out = {'rows': summary, 'detail_sha256': sha(path), 'candidate_count': len(sig),
           'unknown_rank_hours': 240, 'raw_potential_events_during_unknown_rank_hours': 182,
           'tape_audit_sha256': sha(H / '一秒逐笔独立样本核验.json'),
           'risk_audit_sha256': sha(H / '风险来源与账本独立核验.json'),
           'oi_audit_sha256': sha(H / '持仓量逐点独立核验.json'),
           'code_sha256': sha(Path(__file__)),
           'note': 'Unit opportunities only, retrospective selected universe, no true fills or account equity.'}
    (H / '二零二二一秒回测汇总.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT90_SUMMARY', json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
