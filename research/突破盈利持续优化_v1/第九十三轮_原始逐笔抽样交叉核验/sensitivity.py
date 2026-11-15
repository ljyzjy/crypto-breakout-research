"""Reclassify only raw/aggregate sample disagreements as unknown, conservatively."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def metrics(rows, slip):
    values = []
    for x in rows:
        side, fill, raw, funding = int(x['side']), D(x['entry_fill']), D(x['exit_raw']), D(x['funding'])
        ex = raw * (1 - D(side) * slip)
        values.append(D(side) * (ex - fill) / fill - D('.0005') - D('.0005') * ex / fill - funding)
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    return {'trades': len(values), 'net_wins': len(wins), 'net_win_rate_pct': float(100 * len(wins) / len(values)) if values else None,
            'mean_net_pct_notional': float(100 * sum(values) / len(values)) if values else None,
            'profit_factor': float(sum(wins) / -sum(losses)) if losses else None,
            'active_utc_days': len({pd.Timestamp(int(x['entry_ts']), unit='ms', tz='UTC').strftime('%Y-%m-%d') for x in rows})}


def main():
    raw = json.loads((H / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    assert raw['frozen_sha256'] == sha(H / '冻结时点.json') and raw['code_sha256'] == sha(H / 'compare_raw_aggregate.py')
    audit_raw = json.loads((H / '原始逐笔独立核验.json').read_text(encoding='utf-8'))
    assert audit_raw['all_checks_pass'] and audit_raw['source_sha256'] == sha(H / '原始聚合逐笔样本对照.json')
    assert audit_raw['code_sha256'] == sha(H / 'audit_raw_samples.py')
    affected = {x['observation_id'] for x in raw['samples'] if x['status'] != 'agree'}
    summary = json.loads((R90 / '二零二二一秒回测汇总.json').read_text(encoding='utf-8'))
    audit = json.loads((R90 / '二零二二汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['report_sha256'] == sha(R90 / '二零二二一秒回测汇总.json')
    d = pd.read_csv(R90 / '二零二二候选状态及单位账本.csv', dtype=str, keep_default_na=False)
    out = []
    for row in summary['rows']:
        g = d[(d.holding_rule == row['holding_rule']) & (d.leverage == str(row['leverage'])) & (d.cohort == row['cohort'])]
        assert len(g) == 310
        newly_unknown = int((g.observation_id.isin(affected) & ~g.category.eq('unknown')).sum())
        trades = g[g.category.eq('trade') & ~g.observation_id.isin(affected)].to_dict('records')
        slip = D(str(row['exit_slippage_pct'])) / 100
        result = metrics(trades, slip)
        out.append({'holding_rule': row['holding_rule'], 'leverage': row['leverage'], 'cohort': row['cohort'],
                    'exit_slippage_pct': row['exit_slippage_pct'], 'baseline_trades': row['trades'],
                    'baseline_unknown': row['unknown_candidates'], 'newly_unknown': newly_unknown,
                    'sensitivity_unknown': row['unknown_candidates'] + newly_unknown, **result})
    result = {'rows': out, 'affected_observation_ids': sorted(affected),
              'raw_comparison_sha256': sha(H / '原始聚合逐笔样本对照.json'),
              'raw_audit_sha256': sha(H / '原始逐笔独立核验.json'),
              'baseline_summary_sha256': sha(R90 / '二零二二一秒回测汇总.json'),
              'baseline_detail_sha256': sha(R90 / '二零二二候选状态及单位账本.csv'), 'code_sha256': sha(Path(__file__)),
              'note': 'Only sampled discrepancies removed; unsampled aggregation ambiguity is not resolved. No adjusted wallet or real fills.'}
    (H / '原始数据分歧敏感性.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT93_SENSITIVITY', len(affected), 'affected', len(out), 'groups', flush=True)


if __name__ == '__main__':
    main()
