"""Compare only matched, risk-verified one-second entries at 1R and 2R."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R69 = P / '第六十九轮_一秒观察持仓量门'
sys.path.insert(0, str(R69))
from evaluate_2026_oi_gate import metrics

D = Decimal


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main(year):
    risk_path = H / f'{year}一倍止盈本地风险账本.json'
    risk = json.loads(risk_path.read_text(encoding='utf-8'))
    synthetic = json.loads((H / '一倍止盈账本核验合成测试.json').read_text(encoding='utf-8'))
    assert synthetic['all_checks_pass'] and synthetic['audit_code_sha256'] == sha(H / 'audit_1r_ledger.py')
    assert synthetic['settlement_code_sha256'] == sha(H / 'settle_1r_local.py')
    tape = json.loads((H / f'{year}一倍止盈逐笔独立核验.json').read_text(encoding='utf-8'))
    ledger_audit = json.loads((H / f'{year}一倍止盈账本独立核验.json').read_text(encoding='utf-8'))
    progress = json.loads((H / f'{year}一倍止盈逐笔进度.json').read_text(encoding='utf-8'))
    assert tape['all_checks_pass'] and len(tape['samples']) >= 3 and ledger_audit['all_checks_pass']
    assert ledger_audit['ledger_sha256'] == sha(risk_path) and tape['replay_fingerprint'] == risk['replay_fingerprint']
    assert not progress['errors'] and progress['attempted_groups'] == progress['total_groups']
    assert progress['fingerprint'] == risk['replay_fingerprint']
    snap = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结'
    manifest = json.loads((snap / '完整快照哈希.json').read_text(encoding='utf-8'))
    assert sha(snap / '完整快照哈希.json') == risk['source_snapshot_sha256']
    name = 'batch/动态池单位收益与风险.parquet'
    assert sha(snap / name) == manifest['files'][name]
    old = pd.read_parquet(snap / name)
    old = old[(old.status == 'verified') & (old.risk_status == 'verified') & old.liq_proxy.eq(False)]
    old_map = {(x['observation_id'], x['variant']): x for x in old.to_dict('records')}
    alt_map = {(x['observation_id'], x['variant'].replace('_1r_', '_2r_')): x for x in risk['records']
               if x.get('status') == 'verified' and x.get('risk_status') == 'verified' and x.get('liq_proxy') is False}
    assert len(old_map) == risk['eligible_2r_paths'] and set(alt_map).issubset(old_map)
    gate_snap = R69 / f'{year}冻结结果'
    gate_manifest = json.loads((gate_snap / '冻结哈希.json').read_text(encoding='utf-8'))
    assert gate_manifest['all_checks_pass'] and gate_manifest['year'] == year
    gate_path = gate_snap / f'{year}一秒观察持仓量逐笔.csv'
    assert sha(gate_path) == gate_manifest['files'][gate_path.name]
    with gate_path.open(encoding='utf-8', newline='') as f:
        gate = {(x['observation_id'], x['variant']): x['gate'] for x in csv.DictReader(f)}
    assert set(gate) == set(old_map) and set(gate.values()).issubset({'True', 'False', ''})
    summary_path = gate_snap / f'{year}一秒观察持仓量对照.json'
    gate_audit_path = gate_snap / f'{year}持仓量门独立核验.json'
    assert sha(summary_path) == gate_manifest['files'][summary_path.name]
    assert sha(gate_audit_path) == gate_manifest['files'][gate_audit_path.name]
    gate_summary = json.loads(summary_path.read_text(encoding='utf-8'))
    gate_audit = json.loads(gate_audit_path.read_text(encoding='utf-8'))
    assert gate_audit['all_checks_pass'] and gate_audit['result_sha256'] == sha(summary_path)
    outputs = []
    for lev in (10, 20):
        variant = f'one_observation_2r_{lev}x'
        for cohort in ('base', 'oi_gate'):
            baseline = next(x for x in gate_summary['rows'] if x['leverage'] == lev and x['strategy'] == cohort and x['exit_slippage_pct'] == .05)
            universe = [k for k in old_map if k[1] == variant and (cohort == 'base' or gate[k] == 'True')]
            assert len(universe) == baseline['known_trades']
            paired = [k for k in universe if k in alt_map]
            unknown = int(baseline['unknown_candidates']) + len(universe) - len(paired)
            for slip in (D('.0005'), D('.00075'), D('.001')):
                for target in ('1r', '2r'):
                    records = []
                    for k in paired:
                        x = alt_map[k] if target == '1r' else old_map[k]
                        entry = D(str(x['entry_fill']))
                        exit_ = D(str(x['exit_raw'])) * (D(1) - D(int(x['side'])) * slip)
                        net = D(int(x['side'])) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - D(str(x['funding']))
                        if slip == D('.0005'):
                            assert abs(net - D(str(x['net_per_unit_notional']))) < D('1e-11')
                        records.append({'entry_ts': int(x['entry_ts']), 'net': net})
                    outputs.append({'leverage': lev, 'cohort': cohort, 'exit_target': target,
                                    'exit_slippage_pct': float(100 * slip), **metrics(records, unknown),
                                    'eligible_2r_trades': len(universe), 'additional_unpaired_unknown': len(universe) - len(paired),
                                    'known_no_order': baseline['known_no_order']})
    result = {'year': year, 'rows': outputs, 'inputs': {'risk_ledger_sha256': sha(risk_path),
              'ledger_audit_sha256': sha(H / f'{year}一倍止盈账本独立核验.json'),
              'tape_audit_sha256': sha(H / f'{year}一倍止盈逐笔独立核验.json'),
              'prior_gate_csv_sha256': sha(gate_path), 'prior_gate_audit_sha256': sha(gate_audit_path),
              'code_sha256': sha(Path(__file__))},
              'note': 'Only matched entries; static costs and historical exploration; no shared-account simulation.'}
    (H / f'{year}一倍止盈配对对照.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in outputs:
        if row['leverage'] == 20 and row['exit_slippage_pct'] == .05:
            print('ONEOBS_1R_PAIRED', year, row, flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2024', '2026')
    main(sys.argv[1])
