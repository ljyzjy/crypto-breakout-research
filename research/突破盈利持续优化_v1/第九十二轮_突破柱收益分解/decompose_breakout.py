"""Decompose completed candle movement around already-verified market-entry proxies."""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import run_wallet_2022 as wallet
D = Decimal
M = 60000


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    wallet.runner.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and not frozen['2022_pnl_viewed_before_freeze']
    for name, path in frozen['source_paths'].items(): assert sha(Path(path)) == frozen['source_sha256'][name]
    audit = json.loads((R90 / '二零二二汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['report_sha256'] == sha(R90 / '二零二二一秒回测汇总.json')
    supplement = json.loads((R90 / '二零二二日档补源质量.json').read_text(encoding='utf-8'))
    sources = {x['symbol']: x for x in supplement['selected_sources']}
    signals = pd.read_parquet(R90 / '一秒回放批次/动态池逐笔信号筛查.parquet').set_index('observation_id').to_dict('index')
    ledger = pd.read_parquet(R90 / '一秒回放批次/动态池单位收益与风险.parquet')
    ledger = {(x['observation_id'], x['holding_rule'], x['variant']): x for x in ledger.to_dict('records')}
    records = wallet.load_records(); by_symbol = {}
    for r in records:
        sym = signals[r['observation_id']]['contract']
        by_symbol.setdefault(sym, []).append(r)
    details = []
    for symbol, group in sorted(by_symbol.items()):
        wallet.runner.guard()
        source = sources[symbol]; assert sha(Path(source['path'])) == source['sha256']
        bars = pd.read_parquet(source['path'], columns=['ts', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']).set_index('ts')
        assert bars.index.is_unique
        for r in group:
            s = signals[r['observation_id']]
            z = ledger[(r['observation_id'], r['period'], r['variant'])]
            q, side, atr = int(s['quarter_start']), int(r['side']), D(str(s['atr']))
            assert q == int(r['decision_ts']) // 900000 * 900000 and atr > 0
            bar = bars.reindex(range(q, q + 15 * M, M))
            item = {'observation_id': r['observation_id'], 'holding_rule': r['period'], 'leverage': r['leverage'],
                    'symbol': symbol, 'quarter_start': q, 'side': side, 'atr': str(atr), 'status': 'unknown_bar'}
            x = bar[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']].to_numpy(float)
            if len(bar) == 15 and np.isfinite(x).all() and (x > 0).all():
                open_, close = D(str(bar.open.iloc[0])), D(str(bar.close.iloc[-1]))
                entry, entry_raw, exit_raw = D(r['entry_fill']), D(str(z['entry_raw'])), D(str(z['exit_raw']))
                full = D(side) * (close - open_) / entry
                before = D(side) * (entry_raw - open_) / entry
                after = D(side) * (close - entry_raw) / entry
                held = D(side) * (exit_raw - entry_raw) / entry
                assert abs(full - before - after) < D('1e-20')
                item.update(status='verified', quarter_open=str(open_), quarter_close=str(close), entry_fill=str(entry),
                            entry_raw=str(entry_raw), exit_raw=str(exit_raw), large_aligned=str(D(side) * (close - open_) >= atr),
                            entire_pct=str(full * 100), before_entry_pct=str(before * 100), after_entry_to_close_pct=str(after * 100),
                            actual_raw_held_pct=str(held * 100), actual_net_pct=str(D(str(z['net_per_unit_notional'])) * 100))
            details.append(item)
    assert len(details) == len(records)
    columns = ['observation_id', 'holding_rule', 'leverage', 'symbol', 'quarter_start', 'side', 'atr', 'status',
               'quarter_open', 'quarter_close', 'entry_fill', 'entry_raw', 'exit_raw', 'large_aligned', 'entire_pct',
               'before_entry_pct', 'after_entry_to_close_pct', 'actual_raw_held_pct', 'actual_net_pct']
    path = H / '突破柱逐笔分解.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns); writer.writeheader(); writer.writerows(details)
    table = []
    for holding in ('original', 'extended'):
      for lev in (10, 20):
        all_ = [x for x in details if x['holding_rule'] == holding and x['leverage'] == lev]
        known = [x for x in all_ if x['status'] == 'verified']
        for group in ('all', 'large_aligned', 'other'):
            selected = known if group == 'all' else [x for x in known if (x['large_aligned'] == 'True') == (group == 'large_aligned')]
            keys = ('entire_pct', 'before_entry_pct', 'after_entry_to_close_pct', 'actual_raw_held_pct', 'actual_net_pct')
            means = {f'mean_{k}': float(sum(D(x[k]) for x in selected) / len(selected)) if selected else None for k in keys}
            table.append({'holding_rule': holding, 'leverage': lev, 'group': group, 'trades_with_known_bar': len(selected),
                          'net_wins': sum(D(x['actual_net_pct']) > 0 for x in selected), 'unknown_bar_count': len(all_) - len(known), **means})
    out = {'rows': table, 'detail_sha256': sha(path), 'frozen_sha256': sha(H / '冻结时点.json'),
           'audit90_sha256': sha(R90 / '二零二二汇总独立核验.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Ex post body >= 1 historical ATR labels completed candles, not live signals or the capture rate of all large candles.'}
    (H / '突破柱收益分解.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT92_DECOMPOSED', len(details), 'paths', flush=True)


if __name__ == '__main__':
    main()
