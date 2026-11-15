"""Independently recalculate every unknown adjustment and cost-stressed result."""
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def main():
    path = H / '原始数据分歧敏感性.json'
    out = json.loads(path.read_text(encoding='utf-8'))
    raw = json.loads((H / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    assert out['code_sha256'] == sha(H / 'sensitivity.py') and out['raw_comparison_sha256'] == sha(H / '原始聚合逐笔样本对照.json')
    assert out['raw_audit_sha256'] == sha(H / '原始逐笔独立核验.json')
    assert out['baseline_summary_sha256'] == sha(R90 / '二零二二一秒回测汇总.json')
    assert out['baseline_detail_sha256'] == sha(R90 / '二零二二候选状态及单位账本.csv')
    affected = {x['observation_id'] for x in raw['samples'] if x['status'] != 'agree'}
    assert affected == set(out['affected_observation_ids'])
    data = pd.read_csv(R90 / '二零二二候选状态及单位账本.csv', dtype=str, keep_default_na=False)
    baseline = json.loads((R90 / '二零二二一秒回测汇总.json').read_text(encoding='utf-8'))
    for row in out['rows']:
        g = data[(data.holding_rule == row['holding_rule']) & (data.leverage == str(row['leverage'])) & (data.cohort == row['cohort'])]
        old = next(x for x in baseline['rows'] if x['holding_rule'] == row['holding_rule'] and x['leverage'] == row['leverage']
                   and x['cohort'] == row['cohort'] and x['exit_slippage_pct'] == row['exit_slippage_pct'])
        added = sum(x['observation_id'] in affected and x['category'] != 'unknown' for x in g.to_dict('records'))
        assert added == row['newly_unknown'] and row['baseline_unknown'] == old['unknown_candidates']
        assert row['sensitivity_unknown'] == old['unknown_candidates'] + added and row['baseline_trades'] == old['trades']
        trades = g[g.category.eq('trade') & ~g.observation_id.isin(affected)].to_dict('records')
        values = []
        for x in trades:
            side, entry, rawpx, fund = int(x['side']), D(x['entry_fill']), D(x['exit_raw']), D(x['funding'])
            exit_ = rawpx * (1 - D(side) * D(str(row['exit_slippage_pct'])) / 100)
            values.append(D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - fund)
        pos, neg = [x for x in values if x > 0], [x for x in values if x < 0]
        assert row['trades'] == len(values) and row['net_wins'] == len(pos)
        assert near(row['net_win_rate_pct'], 100 * len(pos) / len(values) if values else None)
        assert near(row['mean_net_pct_notional'], 100 * sum(values) / len(values) if values else None)
        assert near(row['profit_factor'], sum(pos) / -sum(neg) if neg else None)
        days = {pd.Timestamp(int(x['entry_ts']), unit='ms', tz='UTC').strftime('%Y-%m-%d') for x in trades}
        assert row['active_utc_days'] == len(days)
    audit = {'all_checks_pass': True, 'groups_checked': len(out['rows']), 'result_sha256': sha(path),
             'code_sha256': sha(Path(__file__)), 'note': 'Arithmetic reclassification only; unsampled records remain unaudited against raw trades.'}
    (H / '敏感性独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT93_SENSITIVITY_AUDIT', json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
