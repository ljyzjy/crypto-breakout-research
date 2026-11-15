"""Independently rederive every candidate classification and all summary rows."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
B = H / '一秒回放批次'
KNOWN = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    result_path = H / '八至十月一秒观察结果.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'summarize.py') and result['frozen_sha256'] == sha(H / '冻结时点.json')
    assert result['risk_audit_sha256'] == sha(H / '风险来源与账本独立核验.json')
    assert result['tape_audit_sha256'] == sha(H / '一秒逐笔独立样本核验.json')
    assert result['ledger_sha256'] == sha(B / '动态池单位收益与风险.parquet')
    detail_path = H / '八至十月候选状态与账本.csv'
    assert result['detail_sha256'] == sha(detail_path)
    with detail_path.open(encoding='utf-8', newline='') as f:
        detail = {(x['observation_id'], int(x['leverage'])): x for x in csv.DictReader(f)}
    sig = pd.read_parquet(B / '动态池逐笔信号筛查.parquet').to_dict('records')
    paths = {(x['observation_id'], x['variant']): x for x in pd.read_parquet(B / '动态池延迟市价路径.parquet').to_dict('records')}
    ledger = {(x['observation_id'], x['variant']): x for x in pd.read_parquet(B / '动态池单位收益与风险.parquet').to_dict('records')}
    assert len(sig) == 57 and len(detail) == 114 and len(result['rows']) == 6
    for lev in (10, 20):
        trades, unknown, no_order = [], 0, 0
        var = f'one_observation_2r_{lev}x'
        for event in sig:
            key = event['observation_id'], var
            status = event['status']
            if status not in KNOWN:
                category = 'unknown'
            elif status != 'qualified':
                category = 'no_order'
            else:
                pre = event[f'precheck_{lev}x']
                if pd.isna(pre): category = 'unknown'
                elif pre != 'passed': category = 'no_order'
                elif key not in paths or paths[key]['status'] != 'verified': category = 'unknown'
                elif key not in ledger or ledger[key]['risk_status'] != 'verified': category = 'unknown'
                elif bool(ledger[key]['liq_proxy']): category = 'unknown'
                else: category = 'trade'
            row = detail[(event['observation_id'], lev)]
            assert row['signal_status'] == status and row['category'] == category
            if category == 'no_order': no_order += 1
            elif category == 'unknown': unknown += 1
            else:
                actual = ledger[key]
                for field in ('entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding'):
                    assert near(row[field], actual[field])
                trades.append(actual)
        assert len(trades) + no_order + unknown == 57
        for out in (x for x in result['rows'] if x['leverage'] == lev):
            assert out['candidate_events'] == 57 and out['known_no_order'] == no_order and out['unknown_candidates'] == unknown
            vals, days = [], set()
            for x in trades:
                side, entry, raw = int(x['side']), float(x['entry_fill']), float(x['exit_raw'])
                exit_ = raw * (1 - side * out['exit_slippage_pct'] / 100)
                vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(x['funding']))
                days.add(datetime.fromtimestamp(int(x['entry_ts']) / 1000, timezone.utc).date())
            n, w = len(vals), sum(v > 0 for v in vals)
            pos, neg = math.fsum(v for v in vals if v > 0), -math.fsum(v for v in vals if v < 0)
            assert out['known_trades'] == n and out['net_wins'] == w and out['active_utc_days'] == len(days)
            assert near(out['net_win_rate_pct'], 100 * w / n if n else None)
            assert near(out['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
            assert near(out['profit_factor'], pos / neg if neg else None)
            assert near(out['worst_net_pct_notional'], 100 * min(vals) if n else None)
            assert near(out['optimistic_win_rate_pct'], 100 * (w + unknown) / (n + unknown) if n + unknown else None)
    out = {'all_checks_pass': True, 'candidate_leverage_rows_checked': len(detail), 'summary_groups_checked': len(result['rows']),
           'result_sha256': sha(result_path), 'detail_sha256': sha(detail_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Classification and arithmetic verification; still historical unit paths, not account equity.'}
    (H / '八至十月汇总独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_SUMMARY_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
