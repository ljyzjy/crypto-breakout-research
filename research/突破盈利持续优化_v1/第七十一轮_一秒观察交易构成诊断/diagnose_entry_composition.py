"""Post-hoc decomposition of one-second vs legacy five-second observations."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import statistics

import pandas as pd

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent
R62 = P / '第六十二轮_一秒观察更早突破'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def stats(rows):
    values = [D(str(r['net_per_unit_notional'])) for r in rows]
    return {'trades': len(values), 'net_wins': sum(x > 0 for x in values),
            'mean_net_pct_notional': float(100 * sum(values) / len(values)) if values else None}


def main():
    output, detail, hashes = [], [], {}
    for year in ('2024', '2026'):
        snap = R62 / f'{year}完整批次_冻结'
        mf = snap / '完整快照哈希.json'
        manifest = json.loads(mf.read_text(encoding='utf-8'))
        assert manifest['all_checks_pass']
        names = ['batch/动态池单位收益与风险.parquet', f'support/{year}一秒观察对照.json', f'support/{year}输入冻结哈希.json']
        for name in names:
            assert sha(snap / name) == manifest['files'][name]
        old_path = snap / 'input/baseline_ledger.parquet'
        if old_path.exists():
            assert sha(old_path) == manifest['files']['input/baseline_ledger.parquet']
        else:
            old_path = R62 / f'{year}冻结输入/baseline_ledger.parquet'
            inputs = json.loads((snap / names[2]).read_text(encoding='utf-8'))
            assert sha(old_path) == inputs['input_sha256']['baseline_ledger.parquet']
        hashes[year] = {'snapshot': sha(mf), 'old_ledger': sha(old_path)}
        old = pd.read_parquet(old_path)
        new = pd.read_parquet(snap / names[0])
        reference = json.loads((snap / names[1]).read_text(encoding='utf-8'))
        for lev in (10, 20):
            def index(d, variant):
                rows = d[(d.variant == variant) & (d.status == 'verified') & (d.risk_status == 'verified') & d.liq_proxy.eq(False)].to_dict('records')
                result = {r['observation_id']: r for r in rows}
                assert len(result) == len(rows)
                return result
            left = index(old, f'normal_2r_{lev}x')
            right = index(new, f'one_observation_2r_{lev}x')
            common, new_only, old_only = set(left) & set(right), set(right) - set(left), set(left) - set(right)
            ref = next(x for x in reference['rows'] if x['leverage'] == lev)
            assert len(common) == ref['common_known_entries']
            assert len(new_only) == ref['new_entries_where_baseline_known_no_order'] and ref['new_entries_where_baseline_unknown'] == 0
            assert len(old_only) == ref['baseline_entries_where_new_known_no_order'] and ref['baseline_entries_where_new_unknown'] == 0
            for obs in common:
                assert left[obs]['side'] == right[obs]['side'] and left[obs]['decision_ts'] == right[obs]['decision_ts']
            delays = [(int(right[x]['entry_ts']) - int(left[x]['entry_ts'])) / 1000 for x in common]
            def rows(d, keys):
                return [d[k] for k in sorted(keys)]
            output.append({'year': year, 'leverage': lev, 'common_five_second': stats(rows(left, common)),
                           'common_one_second': stats(rows(right, common)), 'new_only_one_second': stats(rows(right, new_only)),
                           'old_only_five_second': stats(rows(left, old_only)),
                           'median_new_minus_old_entry_seconds': statistics.median(delays) if delays else None,
                           'unknown_candidates': ref['one_second_observation']['unknown']})
            for group, keys in (('common', common), ('new_only', new_only), ('old_only', old_only)):
                for obs in sorted(keys):
                    a, b = left.get(obs), right.get(obs)
                    detail.append({'year': year, 'leverage': lev, 'group': group, 'observation_id': obs,
                                   'old_entry_ts': a['entry_ts'] if a else '', 'new_entry_ts': b['entry_ts'] if b else '',
                                   'old_net_notional': a['net_per_unit_notional'] if a else '',
                                   'new_net_notional': b['net_per_unit_notional'] if b else ''})
    cols = ['year', 'leverage', 'group', 'observation_id', 'old_entry_ts', 'new_entry_ts', 'old_net_notional', 'new_net_notional']
    with (H / '逐笔构成诊断.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(detail)
    result = {'rows': output, 'source_snapshot_sha256': hashes, 'detail_sha256': sha(H / '逐笔构成诊断.csv'),
              'code_sha256': sha(Path(__file__)), 'note': 'Post-hoc paired decomposition; observation and entry timings both differ; not causal or account results.'}
    (H / '入场构成事后诊断.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in output:
        if row['leverage'] == 20:
            print('ENTRY_COMPOSITION', row, flush=True)


if __name__ == '__main__':
    main()
