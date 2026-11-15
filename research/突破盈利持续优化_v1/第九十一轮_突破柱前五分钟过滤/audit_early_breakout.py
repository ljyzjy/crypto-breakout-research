"""Rebuild pre-entry timing decisions and all fixed cost summaries independently."""
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R90 = P / '第九十轮_二零二二公开行情'
R86 = P / '第八十六轮_首秒追价距离过滤'
R88 = P / '第八十八轮_延长一根柱持有'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def main():
    report_path = H / '前五分钟过滤对照.json'
    out = json.loads(report_path.read_text(encoding='utf-8'))
    detail_path = H / '前五分钟过滤逐笔.csv'
    assert out['frozen_sha256'] == sha(H / '冻结时点.json') and out['code_sha256'] == sha(H / 'evaluate_early_breakout.py')
    assert out['detail_sha256'] == sha(detail_path)
    assert out['audit90_sha256'] == sha(R90 / '二零二二汇总独立核验.json')
    assert out['audit86_sha256'] == sha(R86 / '首秒距离独立核验.json') and out['audit88_sha256'] == sha(R88 / '延长持有配对独立核验.json')
    d = pd.read_csv(detail_path, dtype=str, keep_default_na=False)
    old = pd.read_csv(R86 / '首秒距离逐笔.csv', dtype=str, keep_default_na=False)
    alt = pd.read_csv(R88 / '延长持有配对逐笔.csv', dtype=str, keep_default_na=False)
    prior = {(x['period'], x['observation_id'], x['variant']): x for x in old.to_dict('records')}
    changed = {(x['period'], x['observation_id'], x['variant']): x for x in alt.to_dict('records')}
    l90 = pd.read_parquet(R90 / '一秒回放批次/动态池单位收益与风险.parquet')
    l90 = {(x['observation_id'], x['holding_rule'], x['variant']): x for x in l90.to_dict('records')}
    s90 = pd.read_parquet(R90 / '一秒回放批次/动态池逐笔信号筛查.parquet').set_index('observation_id').to_dict('index')
    categories = pd.read_csv(R90 / '二零二二候选状态及单位账本.csv', dtype=str, keep_default_na=False)
    cat = {(x['observation_id'], x['holding_rule'], x['leverage'], x['cohort']): x['category'] for x in categories.to_dict('records')}
    assert not d.duplicated(['period', 'observation_id', 'leverage', 'holding_rule']).any()
    for x in d.to_dict('records'):
        t, q, lev = int(x['decision_ts']), int(x['quarter_start']), x['leverage']
        assert q == t // 900000 * 900000 and x['early'] == str(t - q < 300000)
        assert int(x['entry_ts']) >= t + 2000
        variant = 'one_observation_2r_' + lev + 'x'
        if x['period'] == '2022':
            z = l90[(x['observation_id'], x['holding_rule'], variant)]
            assert int(s90[x['observation_id']]['quarter_start']) == q and int(z['decision_ts']) == t
            assert near(x['entry_fill'], z['entry_fill']) and near(x['exit_raw'], z['exit_raw']) and near(x['funding'], z['funding'])
            for c in ('base', 'distance', 'oi', 'oi_distance'):
                assert x[c] == str(cat[(x['observation_id'], x['holding_rule'], lev, c)] == 'trade')
        else:
            k = (x['period'], x['observation_id'], variant); z, a = prior[k], changed[k]
            assert int(z['decision_ts']) == t and x['entry_ts'] == z['entry_ts'] and x['side'] == z['side']
            assert near(x['entry_fill'], z['entry_fill']) and x['base'] == 'True'
            for a1, b1 in [('distance', 'extension_gate'), ('oi', 'oi_gate'), ('oi_distance', 'both')]:
                assert x[a1] == z[b1]
            raw = z['exit_raw'] if x['holding_rule'] == 'original' else a['new_exit_raw']
            funding = z['funding'] if x['holding_rule'] == 'original' else a['new_funding']
            assert near(x['exit_raw'], raw) and near(x['funding'], funding)
    assert len(out['rows']) == 864
    for row in out['rows']:
        g = d[(d.holding_rule == row['holding_rule']) & (d.leverage == str(row['leverage'])) & (d[row['cohort']] == 'True')]
        if row['period'] != 'all': g = g[g.period == row['period']]
        if row['timing'] == 'early': g = g[g.early == 'True']
        if row['timing'] == 'later': g = g[g.early == 'False']
        values = []
        for x in g.to_dict('records'):
            side = int(x['side']); entry = D(x['entry_fill']); raw = D(x['exit_raw']); funding = D(x['funding'])
            exit_ = raw * (1 - D(side) * D(str(row['exit_slippage_pct'])) / 100)
            values.append(D(side) * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - funding)
        wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
        days = {pd.Timestamp(int(t), unit='ms', tz='UTC').strftime('%Y-%m-%d') for t in g.entry_ts}
        assert row['known_trades'] == len(values) and row['net_wins'] == len(wins) and row['active_utc_days'] == len(days)
        assert near(row['net_win_rate_pct'], 100 * len(wins) / len(values) if values else None)
        assert near(row['mean_net_pct_notional'], 100 * sum(values) / len(values) if values else None)
        assert near(row['profit_factor'], sum(wins) / -sum(losses) if losses else None)
    result = {'all_checks_pass': True, 'paths_checked': len(d), 'groups_checked': len(out['rows']),
              'result_sha256': sha(report_path), 'detail_sha256': sha(detail_path), 'code_sha256': sha(Path(__file__)),
              'note': 'Checks time gate, source paths and arithmetic; unknown candidates and 2022 unrankable hours stay unresolved.'}
    (H / '前五分钟过滤独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT91_AUDIT_PASS', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
