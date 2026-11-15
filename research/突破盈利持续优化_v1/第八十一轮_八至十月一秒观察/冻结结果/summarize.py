"""Account for every candidate and summarize only independently audited paths."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
B = H / '一秒回放批次'
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics
import run_replay as runner

D = Decimal
getcontext().prec = 40
BENIGN = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    sample = json.loads((H / '一秒逐笔独立样本核验.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    assert sample['all_checks_pass'] and sample['batch_fingerprint'] == runner.fingerprint()
    assert sample['code_sha256'] == sha(H / 'audit_tapes.py')
    assert audit['all_checks_pass'] and audit['input_sha256'] == sha(B / '风险来源与结算.json')
    assert audit['ledger_sha256'] == sha(B / '动态池单位收益与风险.parquet') and audit['code_sha256'] == sha(H / 'audit_risk.py')
    sig = pd.read_parquet(B / '动态池逐笔信号筛查.parquet')
    paths = pd.read_parquet(B / '动态池延迟市价路径.parquet')
    ledger = pd.read_parquet(B / '动态池单位收益与风险.parquet')
    assert len(sig) == 57 and sig.observation_id.is_unique
    paths_by = {(r['observation_id'], r['variant']): r for r in paths.to_dict('records')}
    ledger_by = {(r['observation_id'], r['variant']): r for r in ledger.to_dict('records')}
    detail, rows = [], []
    for lev in (10, 20):
        trades, unknown, no_order = [], 0, 0
        variant = f'one_observation_2r_{lev}x'
        for s in sig.to_dict('records'):
            key = (s['observation_id'], variant)
            status = s['status']
            entry = {'observation_id': s['observation_id'], 'leverage': lev, 'signal_status': status, 'category': '', 'reason': ''}
            if status not in BENIGN:
                entry.update(category='unknown', reason=status)
                unknown += 1
            elif status != 'qualified':
                entry.update(category='no_order', reason=status)
                no_order += 1
            elif pd.isna(s[f'precheck_{lev}x']):
                entry.update(category='unknown', reason='missing_precheck')
                unknown += 1
            elif s[f'precheck_{lev}x'] != 'passed':
                entry.update(category='no_order', reason=s[f'precheck_{lev}x'])
                no_order += 1
            elif key not in paths_by or paths_by[key]['status'] != 'verified':
                entry.update(category='unknown', reason='missing_or_unverified_path')
                unknown += 1
            elif key not in ledger_by or ledger_by[key]['risk_status'] != 'verified':
                entry.update(category='unknown', reason='missing_or_unverified_risk')
                unknown += 1
            elif bool(ledger_by[key]['liq_proxy']):
                entry.update(category='unknown', reason='liquidation_proxy')
                unknown += 1
            else:
                r = ledger_by[key]
                side, fill, raw, funding = int(r['side']), D(str(r['entry_fill'])), D(str(r['exit_raw'])), D(str(r['funding']))
                exit_ = raw * (1 - D(side) * D('.0005'))
                net = D(side) * (exit_ - fill) / fill - D('.0005') - D('.0005') * exit_ / fill - funding
                assert abs(net - D(str(r['net_per_unit_notional']))) < D('1e-11')
                rec = {'entry_ts': int(r['entry_ts']), 'entry_fill': fill, 'exit_raw': raw, 'side': side, 'funding': funding, 'net': net}
                trades.append(rec)
                entry.update(category='trade', reason=r['reason'], **rec)
            detail.append(entry)
        assert len(trades) + unknown + no_order == 57
        for slip in (D('.0005'), D('.00075'), D('.001')):
            tmp = []
            for r in trades:
                exit_ = r['exit_raw'] * (1 - D(r['side']) * slip)
                net = D(r['side']) * (exit_ - r['entry_fill']) / r['entry_fill'] - D('.0005') - D('.0005') * exit_ / r['entry_fill'] - r['funding']
                tmp.append({**r, 'net': net})
            rows.append({'leverage': lev, 'exit_slippage_pct': float(100 * slip),
                         **metrics(tmp, unknown), 'known_no_order': no_order, 'candidate_events': 57})
    cols = ['observation_id', 'leverage', 'signal_status', 'category', 'reason', 'entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding', 'net']
    detail_path = H / '八至十月候选状态与账本.csv'
    with detail_path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(detail)
    output = {'rows': rows, 'detail_sha256': sha(detail_path), 'tape_audit_sha256': sha(H / '一秒逐笔独立样本核验.json'),
              'risk_audit_sha256': sha(H / '风险来源与账本独立核验.json'), 'frozen_sha256': sha(H / '冻结时点.json'),
              'ledger_sha256': sha(B / '动态池单位收益与风险.parquet'), 'code_sha256': sha(Path(__file__)),
              'note': 'Historical unit opportunities; project previously viewed period, not blind; no account simulation.'}
    (H / '八至十月一秒观察结果.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT81_SUMMARY', json.dumps(rows, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
