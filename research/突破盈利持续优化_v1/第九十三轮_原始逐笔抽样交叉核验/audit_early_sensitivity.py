"""Independently recheck all early-gate sample-disagreement sensitivity groups."""
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
R91 = H.parent / '第九十一轮_突破柱前五分钟过滤'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def main():
    path = H / '前五分钟分歧敏感性.json'; result = json.loads(path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'early_sensitivity.py')
    assert result['base_timing_sha256'] == sha(R91 / '前五分钟过滤对照.json') and result['base_detail_sha256'] == sha(R91 / '前五分钟过滤逐笔.csv')
    assert result['raw_sensitivity_sha256'] == sha(H / '原始数据分歧敏感性.json')
    affected = set(result['affected_observation_ids'])
    data = pd.read_csv(R91 / '前五分钟过滤逐笔.csv', dtype=str, keep_default_na=False)
    source = json.loads((R91 / '前五分钟过滤对照.json').read_text(encoding='utf-8'))
    raw = json.loads((H / '原始数据分歧敏感性.json').read_text(encoding='utf-8'))
    def key(x): return tuple(x[k] for k in ('period', 'holding_rule', 'leverage', 'cohort', 'timing', 'exit_slippage_pct'))
    original = {key(x): x for x in source['rows']}; assert len(original) == len(result['rows'])
    for row in result['rows']:
        old = original[key(row)]
        g = data[(data.holding_rule == row['holding_rule']) & (data.leverage == str(row['leverage'])) & (data[row['cohort']] == 'True')]
        if row['period'] != 'all': g = g[g.period.eq(row['period'])]
        if row['timing'] == 'early': g = g[g.early.eq('True')]
        elif row['timing'] == 'later': g = g[g.early.eq('False')]
        if row['period'] in ('2022', 'all'):
            g = g[~(g.period.eq('2022') & g.observation_id.isin(affected))]
            added = next(x['newly_unknown'] for x in raw['rows'] if x['holding_rule'] == row['holding_rule'] and x['leverage'] == row['leverage']
                         and x['cohort'] == row['cohort'] and x['exit_slippage_pct'] == .05)
        else: added = 0
        assert row['unknown_candidates_conservative'] == old['unknown_candidates_conservative'] + added
        values = []
        for x in g.to_dict('records'):
            side, entry, price, funding = int(x['side']), D(x['entry_fill']), D(x['exit_raw']), D(x['funding'])
            ex = price * (1 - D(side) * D(str(row['exit_slippage_pct'])) / 100)
            values.append(D(side) * (ex - entry) / entry - D('.0005') - D('.0005') * ex / entry - funding)
        wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
        assert row['known_trades'] == len(values) and row['net_wins'] == len(wins)
        assert near(row['net_win_rate_pct'], 100 * len(wins) / len(values) if values else None)
        assert near(row['mean_net_pct_notional'], 100 * sum(values) / len(values) if values else None)
        assert near(row['profit_factor'], sum(wins) / -sum(losses) if losses else None)
        assert row['active_utc_days'] == len({pd.Timestamp(int(t), unit='ms', tz='UTC').strftime('%Y-%m-%d') for t in g.entry_ts})
    out = {'all_checks_pass': True, 'groups_checked': len(result['rows']), 'result_sha256': sha(path),
           'code_sha256': sha(Path(__file__)), 'note': 'Conservative sample reclassification; untested samples and rank hours remain unresolved.'}
    (H / '前五分钟敏感性独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT93_EARLY_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
