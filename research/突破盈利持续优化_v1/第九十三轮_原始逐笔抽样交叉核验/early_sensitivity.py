"""Apply raw-sample uncertainty to the earlier frozen timing comparison."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
R91 = H.parent / '第九十一轮_突破柱前五分钟过滤'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    raw = json.loads((H / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    sens = json.loads((H / '原始数据分歧敏感性.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '敏感性独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '原始数据分歧敏感性.json')
    source = json.loads((R91 / '前五分钟过滤对照.json').read_text(encoding='utf-8'))
    proof = json.loads((R91 / '前五分钟过滤独立核验.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['result_sha256'] == sha(R91 / '前五分钟过滤对照.json')
    affected = {x['observation_id'] for x in raw['samples'] if x['status'] != 'agree'}
    detail = pd.read_csv(R91 / '前五分钟过滤逐笔.csv', dtype=str, keep_default_na=False)
    rows = []
    for row in source['rows']:
        g = detail[(detail.holding_rule == row['holding_rule']) & (detail.leverage == str(row['leverage'])) & (detail[row['cohort']] == 'True')]
        if row['period'] != 'all': g = g[g.period.eq(row['period'])]
        if row['timing'] == 'early': g = g[g.early.eq('True')]
        if row['timing'] == 'later': g = g[g.early.eq('False')]
        if row['period'] in ('2022', 'all'):
            g = g[~(g.period.eq('2022') & g.observation_id.isin(affected))]
            added = next(x['newly_unknown'] for x in sens['rows'] if x['holding_rule'] == row['holding_rule']
                         and x['leverage'] == row['leverage'] and x['cohort'] == row['cohort'] and x['exit_slippage_pct'] == .05)
        else: added = 0
        slip = D(str(row['exit_slippage_pct'])) / 100
        vals = []
        for x in g.to_dict('records'):
            side, fill, rawpx, fund = int(x['side']), D(x['entry_fill']), D(x['exit_raw']), D(x['funding'])
            exit_ = rawpx * (1 - D(side) * slip)
            vals.append(D(side) * (exit_ - fill) / fill - D('.0005') - D('.0005') * exit_ / fill - fund)
        wins, losses = [x for x in vals if x > 0], [x for x in vals if x < 0]
        rows.append({**{k: row[k] for k in ('period', 'holding_rule', 'leverage', 'cohort', 'timing', 'exit_slippage_pct')},
                     'known_trades': len(vals), 'net_wins': len(wins),
                     'net_win_rate_pct': float(100 * len(wins) / len(vals)) if vals else None,
                     'mean_net_pct_notional': float(100 * sum(vals) / len(vals)) if vals else None,
                     'profit_factor': float(sum(wins) / -sum(losses)) if losses else None,
                     'active_utc_days': len({pd.Timestamp(int(t), unit='ms', tz='UTC').strftime('%Y-%m-%d') for t in g.entry_ts}),
                     'unknown_candidates_conservative': row['unknown_candidates_conservative'] + added})
    result = {'rows': rows, 'affected_observation_ids': sorted(affected), 'base_timing_sha256': sha(R91 / '前五分钟过滤对照.json'),
              'base_detail_sha256': sha(R91 / '前五分钟过滤逐笔.csv'), 'raw_sensitivity_sha256': sha(H / '原始数据分歧敏感性.json'),
              'code_sha256': sha(Path(__file__)),
              'note': 'Only sampled source discrepancies excluded; no claim about unsampled events or account equity.'}
    (H / '前五分钟分歧敏感性.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT93_EARLY_SENSITIVITY', len(rows), 'groups', flush=True)


if __name__ == '__main__':
    main()
