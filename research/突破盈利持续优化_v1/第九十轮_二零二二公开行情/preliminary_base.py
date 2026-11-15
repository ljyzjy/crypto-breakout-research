"""Report risk-audited base paths while OI and account verification are pending."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
B = H / '一秒回放批次'
D = Decimal
BENIGN = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((H / '风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['ledger_sha256'] == sha(B / '动态池单位收益与风险.parquet')
    tape = json.loads((H / '一秒逐笔独立样本核验.json').read_text(encoding='utf-8')); assert tape['all_checks_pass']
    sig = pd.read_parquet(B / '动态池逐笔信号筛查.parquet')
    paths = pd.read_parquet(B / '动态池延迟市价路径.parquet')
    ledger = pd.read_parquet(B / '动态池单位收益与风险.parquet')
    p = {(r['observation_id'], r['holding_rule'], r['variant']): r for r in paths.to_dict('records')}
    l = {(r['observation_id'], r['holding_rule'], r['variant']): r for r in ledger.to_dict('records')}
    rows = []
    for holding in ('original', 'extended'):
      for lev in (10, 20):
        trades, unknown, no_order = [], 0, 0
        for s in sig.to_dict('records'):
            key = s['observation_id'], holding, f'one_observation_2r_{lev}x'
            if s['status'] not in BENIGN: unknown += 1
            elif s['status'] != 'qualified': no_order += 1
            elif pd.isna(s[f'precheck_{lev}x']): unknown += 1
            elif s[f'precheck_{lev}x'] != 'passed': no_order += 1
            elif key not in p or p[key]['status'] != 'verified' or key not in l or l[key]['risk_status'] != 'verified' or bool(l[key]['liq_proxy']): unknown += 1
            else:
                r = l[key]; side, entry, raw, funding = int(r['side']), D(str(r['entry_fill'])), D(str(r['exit_raw'])), D(str(r['funding']))
                ex = raw * (1 - D(side) * D('.0005'))
                net = D(side) * (ex - entry) / entry - D('.0005') - D('.0005') * ex / entry - funding
                assert abs(net - D(str(r['net_per_unit_notional']))) < D('1e-11')
                trades.append((net, int(r['entry_ts'])))
        assert len(trades) + unknown + no_order == len(sig) == 310
        values = [x[0] for x in trades]; wins = [x for x in values if x > 0]; loss = [x for x in values if x < 0]
        rows.append({'holding_rule': holding, 'leverage': lev, 'known_trades': len(values), 'wins': len(wins),
                     'net_win_rate_pct': float(D(100) * len(wins) / len(values)) if values else None,
                     'mean_net_pct_notional': float(D(100) * sum(values) / len(values)) if values else None,
                     'profit_factor': float(sum(wins) / -sum(loss)) if loss else None,
                     'active_utc_days': len({pd.Timestamp(t, unit='ms', tz='UTC').strftime('%Y-%m-%d') for _, t in trades}),
                     'unknown_candidates': unknown, 'known_no_order': no_order})
    out = {'rows': rows, 'risk_audit_sha256': sha(H / '风险来源与账本独立核验.json'),
           'tape_audit_sha256': sha(H / '一秒逐笔独立样本核验.json'), 'code_sha256': sha(Path(__file__)),
           'unknown_rank_hours': 240, 'note': 'Preliminary base only; OI, independent classifications, raw sample, account and future validation pending.'}
    (H / '基础方案暂定统计.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT90_PRELIMINARY', json.dumps(rows, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
