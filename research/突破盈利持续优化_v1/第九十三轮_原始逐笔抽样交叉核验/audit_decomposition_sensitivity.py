"""Independently verify the sampled-conflict candle decomposition adjustment."""
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
R92 = H.parent / '第九十二轮_突破柱收益分解'
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def main():
    path = H / '突破柱分解敏感性.json'; out = json.loads(path.read_text(encoding='utf-8'))
    assert out['code_sha256'] == sha(H / 'decomposition_sensitivity.py')
    assert out['source_detail_sha256'] == sha(R92 / '突破柱逐笔分解.csv') and out['raw_comparison_sha256'] == sha(H / '原始聚合逐笔样本对照.json')
    raw = json.loads((H / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    affected = {x['observation_id'] for x in raw['samples'] if x['status'] != 'agree'}
    assert affected == set(out['affected_observation_ids'])
    d = pd.read_csv(R92 / '突破柱逐笔分解.csv', dtype=str, keep_default_na=False)
    for row in out['rows']:
        all_ = d[(d.holding_rule == row['holding_rule']) & (d.leverage == str(row['leverage']))]
        known = all_[all_.status.eq('verified') & ~all_.observation_id.isin(affected)]
        if row['group'] != 'all': known = known[known.large_aligned.eq(str(row['group'] == 'large_aligned'))]
        assert row['trades_with_known_bar'] == len(known) and row['net_wins'] == sum(D(x) > 0 for x in known.actual_net_pct)
        assert row['removed_source_conflict'] == int(all_.observation_id.isin(affected).sum())
        assert row['unknown_bar_count'] == int(all_.status.ne('verified').sum())
        for key in ('entire_pct', 'before_entry_pct', 'after_entry_to_close_pct', 'actual_raw_held_pct', 'actual_net_pct'):
            expected = sum(D(x) for x in known[key]) / len(known) if len(known) else None
            assert near(row['mean_' + key], expected)
    audit = {'all_checks_pass': True, 'groups_checked': len(out['rows']), 'result_sha256': sha(path), 'code_sha256': sha(Path(__file__)),
             'note': 'Ex post diagnostic only, with sampled conflicts excluded.'}
    (H / '突破柱敏感性独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT93_BREAKDOWN_AUDIT', json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
