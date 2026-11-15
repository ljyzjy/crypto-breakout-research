"""Recompute candle decomposition after removing sampled source conflicts."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
R92 = H.parent / '第九十二轮_突破柱收益分解'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((R92 / '突破柱分解独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(R92 / '突破柱收益分解.json')
    raw = json.loads((H / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    affected = {x['observation_id'] for x in raw['samples'] if x['status'] != 'agree'}
    d = pd.read_csv(R92 / '突破柱逐笔分解.csv', dtype=str, keep_default_na=False)
    rows = []
    for holding in ('original', 'extended'):
      for lev in (10, 20):
        all_ = d[(d.holding_rule == holding) & (d.leverage == str(lev))]
        removed = int(all_.observation_id.isin(affected).sum())
        known = all_[all_.status.eq('verified') & ~all_.observation_id.isin(affected)]
        for group in ('all', 'large_aligned', 'other'):
            g = known if group == 'all' else known[known.large_aligned.eq(str(group == 'large_aligned'))]
            keys = ('entire_pct', 'before_entry_pct', 'after_entry_to_close_pct', 'actual_raw_held_pct', 'actual_net_pct')
            means = {f'mean_{k}': float(sum(D(x) for x in g[k]) / len(g)) if len(g) else None for k in keys}
            rows.append({'holding_rule': holding, 'leverage': lev, 'group': group, 'trades_with_known_bar': len(g),
                         'net_wins': sum(D(x) > 0 for x in g.actual_net_pct), 'removed_source_conflict': removed,
                         'unknown_bar_count': int(all_.status.ne('verified').sum()), **means})
    out = {'rows': rows, 'affected_observation_ids': sorted(affected), 'source_detail_sha256': sha(R92 / '突破柱逐笔分解.csv'),
           'raw_comparison_sha256': sha(H / '原始聚合逐笔样本对照.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Ex-post labels after excluding sampled conflicts; no live large-candle signal or market-wide capture rate.'}
    (H / '突破柱分解敏感性.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT93_BREAKDOWN_SENSITIVITY', len(rows), 'groups', flush=True)


if __name__ == '__main__':
    main()
