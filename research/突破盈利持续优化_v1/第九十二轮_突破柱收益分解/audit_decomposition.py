"""Independently check raw minute candles, price decomposition and summaries."""
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def main():
    runner.guard(start=True)
    result_path = H / '突破柱收益分解.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    detail_path = H / '突破柱逐笔分解.csv'
    assert result['detail_sha256'] == sha(detail_path) and result['code_sha256'] == sha(H / 'decompose_breakout.py')
    assert result['frozen_sha256'] == sha(H / '冻结时点.json') and result['audit90_sha256'] == sha(R90 / '二零二二汇总独立核验.json')
    supplement = json.loads((R90 / '二零二二日档补源质量.json').read_text(encoding='utf-8'))
    sources = {x['symbol']: x for x in supplement['selected_sources']}
    signals = pd.read_parquet(R90 / '一秒回放批次/动态池逐笔信号筛查.parquet').set_index('observation_id').to_dict('index')
    ledger = pd.read_parquet(R90 / '一秒回放批次/动态池单位收益与风险.parquet')
    ledger = {(x['observation_id'], x['holding_rule'], x['variant']): x for x in ledger.to_dict('records')}
    detail = pd.read_csv(detail_path, dtype=str, keep_default_na=False)
    assert not detail.duplicated(['observation_id', 'holding_rule', 'leverage']).any()
    checked = 0
    for symbol, group in detail.groupby('symbol'):
        runner.guard()
        source = sources[symbol]; assert sha(Path(source['path'])) == source['sha256']
        frame = pd.read_parquet(source['path']).set_index('ts')
        for x in group.to_dict('records'):
            s = signals[x['observation_id']]; variant = 'one_observation_2r_' + x['leverage'] + 'x'
            z = ledger[(x['observation_id'], x['holding_rule'], variant)]
            q, side = int(x['quarter_start']), int(x['side'])
            assert q == int(s['quarter_start']) and side == int(z['side']) and near(x['atr'], s['atr'])
            bars = frame.reindex(range(q, q + 900000, 60000))
            cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']
            data = bars[cols].to_numpy(float); valid = len(bars) == 15 and np.isfinite(data).all() and (data > 0).all()
            assert x['status'] == ('verified' if valid else 'unknown_bar')
            if valid:
                open_, close = D(str(bars.open.iloc[0])), D(str(bars.close.iloc[-1]))
                entry, raw, exit_ = D(str(z['entry_fill'])), D(str(z['entry_raw'])), D(str(z['exit_raw']))
                assert near(x['quarter_open'], open_) and near(x['quarter_close'], close)
                assert near(x['entry_fill'], entry) and near(x['entry_raw'], raw) and near(x['exit_raw'], exit_)
                assert x['large_aligned'] == str(D(side) * (close - open_) >= D(x['atr']))
                assert near(x['entire_pct'], 100 * D(side) * (close - open_) / entry)
                assert near(x['before_entry_pct'], 100 * D(side) * (raw - open_) / entry)
                assert near(x['after_entry_to_close_pct'], 100 * D(side) * (close - raw) / entry)
                assert near(x['actual_raw_held_pct'], 100 * D(side) * (exit_ - raw) / entry)
                assert near(x['actual_net_pct'], 100 * D(str(z['net_per_unit_notional'])))
            checked += 1
    for row in result['rows']:
        all_ = detail[(detail.holding_rule == row['holding_rule']) & (detail.leverage == str(row['leverage']))]
        known = all_[all_.status.eq('verified')]
        group = known if row['group'] == 'all' else known[known.large_aligned.eq(str(row['group'] == 'large_aligned'))]
        assert row['unknown_bar_count'] == len(all_) - len(known) and row['trades_with_known_bar'] == len(group)
        assert row['net_wins'] == sum(D(x) > 0 for x in group.actual_net_pct)
        for k in ('entire_pct', 'before_entry_pct', 'after_entry_to_close_pct', 'actual_raw_held_pct', 'actual_net_pct'):
            expected = sum(D(x) for x in group[k]) / len(group) if len(group) else None
            assert near(row['mean_' + k], expected)
    out = {'all_checks_pass': True, 'path_rows_checked': checked, 'summary_groups_checked': len(result['rows']),
           'result_sha256': sha(result_path), 'detail_sha256': sha(detail_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Historical close is used only for an ex-post label; results do not measure capture rate of all big candles.'}
    (H / '突破柱分解独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT92_AUDIT_PASS', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
