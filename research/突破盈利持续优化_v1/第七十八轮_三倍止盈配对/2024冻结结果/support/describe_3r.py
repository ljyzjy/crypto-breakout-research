"""Compare fixed 3R and 2R exits on the same audited historical entries."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main(year):
    risk_path = H / f'{year}三倍止盈风险账本.json'
    risk = json.loads(risk_path.read_text(encoding='utf-8'))
    tape = json.loads((H / f'{year}三倍止盈逐笔独立核验.json').read_text(encoding='utf-8'))
    audit = json.loads((H / f'{year}三倍止盈账本独立核验.json').read_text(encoding='utf-8'))
    progress = json.loads((H / f'{year}三倍止盈逐笔进度.json').read_text(encoding='utf-8'))
    assert tape['all_checks_pass'] and len(tape['samples']) >= min(3, progress['total_groups'])
    assert audit['all_checks_pass'] and audit['ledger_sha256'] == sha(risk_path)
    assert progress['attempted_groups'] == progress['total_groups'] and not progress['errors']
    assert progress['fingerprint'] == risk['replay_fingerprint'] == tape['replay_fingerprint']
    base = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
    oi = P / ('第七十三轮_二零二三扩展核验/2023持仓量冻结结果' if year == '2023' else f'第六十九轮_一秒观察持仓量门/{year}冻结结果')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == frozen['plan_sha256']
    assert sha(base / '完整快照哈希.json') == frozen['base_snapshots'][year] == risk['source_snapshot_sha256']
    assert sha(oi / '冻结哈希.json') == frozen['oi_snapshots'][year]
    bm, om = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8')), json.loads((oi / '冻结哈希.json').read_text(encoding='utf-8'))
    ledger_path = base / 'batch/动态池单位收益与风险.parquet'
    assert sha(ledger_path) == bm['files']['batch/动态池单位收益与风险.parquet']
    ledger = pd.read_parquet(ledger_path)
    ledger = ledger[(ledger.status == 'verified') & (ledger.risk_status == 'verified') & ledger.liq_proxy.eq(False)]
    old = {(x['observation_id'], x['variant']): x for x in ledger.to_dict('records')}
    new = {(x['observation_id'], x['variant'].replace('_3r_', '_2r_')): x for x in risk['records']
           if x.get('status') == x.get('risk_status') == 'verified' and x.get('liq_proxy') is False}
    assert len(old) == risk['eligible_2r_paths'] and set(new).issubset(old)
    gate_path = oi / f'{year}一秒观察持仓量逐笔.csv'
    result_path = oi / ('2023持仓量跨期对照.json' if year == '2023' else f'{year}一秒观察持仓量对照.json')
    assert sha(gate_path) == om['files'][gate_path.name] and sha(result_path) == om['files'][result_path.name]
    with gate_path.open(encoding='utf-8', newline='') as f:
        gates = {(r['observation_id'], r['variant']): r['gate'] for r in csv.DictReader(f)}
    assert set(gates) == set(old)
    prior = json.loads(result_path.read_text(encoding='utf-8'))['rows']
    results, detail = [], []
    for lev in (10, 20):
        variant = f'one_observation_2r_{lev}x'
        for cohort in ('base', 'oi_gate'):
            reference = next(x for x in prior if x['leverage'] == lev and x['strategy'] == cohort and x['exit_slippage_pct'] == .05)
            universe = [k for k in old if k[1] == variant and (cohort == 'base' or gates[k] == 'True')]
            assert len(universe) == reference['known_trades']
            paired = [k for k in universe if k in new]
            unknown = reference['unknown_candidates'] + len(universe) - len(paired)
            for key in paired:
                a, b = old[key], new[key]
                detail.append({'year': year, 'leverage': lev, 'cohort': cohort, 'observation_id': key[0],
                               'entry_ts': int(a['entry_ts']), 'side': int(a['side']),
                               'old_exit_ts': int(a['exit_ts']), 'old_exit_raw': a['exit_raw'], 'old_funding': a['funding'],
                               'old_net': a['net_per_unit_notional'], 'old_reason': a['reason'],
                               'new_exit_ts': int(b['exit_ts']), 'new_exit_raw': b['exit_raw'], 'new_funding': b['funding'],
                               'new_net': b['net_per_unit_notional'], 'new_reason': b['reason'],
                               'entry_fill': a['entry_fill'], 'source_mode': b['source_mode']})
            for slip in (D('.0005'), D('.00075'), D('.001')):
                for target in ('2r', '3r'):
                    records = []
                    for key in paired:
                        x = old[key] if target == '2r' else new[key]
                        entry = D(str(x['entry_fill']))
                        exit_ = D(str(x['exit_raw'])) * (1 - D(int(x['side'])) * slip)
                        net = D(int(x['side'])) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - D(str(x['funding']))
                        if slip == D('.0005'):
                            assert abs(net - D(str(x['net_per_unit_notional']))) < D('1e-11')
                        records.append({'entry_ts': int(x['entry_ts']), 'net': net})
                    results.append({'year': year, 'leverage': lev, 'cohort': cohort, 'exit_target': target,
                                    'exit_slippage_pct': float(100 * slip), **metrics(records, unknown),
                                    'eligible_2r_trades': len(universe), 'additional_unpaired_unknown': len(universe) - len(paired),
                                    'known_no_order': reference['known_no_order']})
    cols = ['year', 'leverage', 'cohort', 'observation_id', 'entry_ts', 'side', 'old_exit_ts', 'old_exit_raw', 'old_funding', 'old_net',
            'old_reason', 'new_exit_ts', 'new_exit_raw', 'new_funding', 'new_net', 'new_reason', 'entry_fill', 'source_mode']
    detail_path = H / f'{year}三倍止盈配对逐笔.csv'
    with detail_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(detail)
    out = {'year': year, 'rows': results, 'risk_ledger_sha256': sha(risk_path), 'ledger_audit_sha256': sha(H / f'{year}三倍止盈账本独立核验.json'),
           'tape_audit_sha256': sha(H / f'{year}三倍止盈逐笔独立核验.json'), 'detail_sha256': sha(detail_path),
           'plan_sha256': sha(H / '冻结研究方案.md'), 'code_sha256': sha(Path(__file__)),
           'note': 'Matched historical entries, static costs; no account or actual fills.'}
    (H / f'{year}三倍止盈配对对照.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in results:
        if row['leverage'] == 20 and row['exit_slippage_pct'] == .05:
            print('THREE_R_PAIRED', row, flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
