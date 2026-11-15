import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '四时段等名义合并.json'
    z = json.loads(path.read_text(encoding='utf-8'))
    assert z['code_sha256'] == sha(H / 'combine_periods.py')
    assert z['current_summary_sha256'] == sha(H / '八至十月一秒观察结果.json')
    assert z['current_audit_sha256'] == sha(H / '八至十月汇总独立核验.json')
    assert z['previous_summary_sha256'] == sha(P / '第七十三轮_二零二三扩展核验/三时段合并单位机会.json')
    assert z['previous_audit_sha256'] == sha(P / '第七十三轮_二零二三扩展核验/三时段合并独立核验.json')
    assert z['detail_sha256'] == sha(H / '四时段已核验逐笔.csv')
    with (H / '四时段已核验逐笔.csv').open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 226 and len({(x['observation_id'], x['variant']) for x in rows}) == 226
    expected = {}
    freeze = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    for year in ('2023', '2024', '2026'):
        folder = P / ('第七十三轮_二零二三扩展核验/2023持仓量冻结结果' if year == '2023' else f'第六十九轮_一秒观察持仓量门/{year}冻结结果')
        manifest = folder / '冻结哈希.json'
        assert sha(manifest) == freeze['oi_snapshots'][year]
        meta = json.loads(manifest.read_text(encoding='utf-8'))
        name = f'{year}一秒观察持仓量逐笔.csv'
        assert sha(folder / name) == meta['files'][name]
        with (folder / name).open(encoding='utf-8', newline='') as f:
            for x in csv.DictReader(f):
                expected[(x['observation_id'], x['variant'])] = (year, x['entry_ts'], x['net'])
    with (H / '八至十月候选状态与账本.csv').open(encoding='utf-8', newline='') as f:
        for x in csv.DictReader(f):
            if x['category'] == 'trade':
                expected[(x['observation_id'], f"one_observation_2r_{x['leverage']}x")] = ('2026_aug_oct', x['entry_ts'], x['net'])
    assert len(expected) == len(rows)
    for x in rows:
        old = expected[(x['observation_id'], x['variant'])]
        assert (x['period'], x['entry_ts']) == old[:2] and near(x['net'], old[2])
    for out in z['rows']:
        selected = [x for x in rows if x['variant'].endswith(f"_{out['leverage']}x")]
        vals = [float(x['net']) for x in selected]
        wins = sum(x > 0 for x in vals)
        positive, negative = math.fsum(x for x in vals if x > 0), -math.fsum(x for x in vals if x < 0)
        days = {datetime.fromtimestamp(int(x['entry_ts']) / 1000, timezone.utc).date() for x in selected}
        assert out['known_trades'] == len(vals) and out['net_wins'] == wins and out['active_utc_days'] == len(days)
        assert out['unknown_candidates'] == 42 and out['candidate_events'] == 361
        assert out['known_no_order'] + len(vals) + out['unknown_candidates'] == 361
        assert near(out['net_win_rate_pct'], 100 * wins / len(vals))
        assert near(out['mean_net_pct_notional'], 100 * math.fsum(vals) / len(vals))
        assert near(out['profit_factor'], positive / negative)
        assert near(out['worst_net_pct_notional'], 100 * min(vals))
    out = {'all_checks_pass': True, 'detail_rows_checked': len(rows), 'groups_checked': len(z['rows']),
           'result_sha256': sha(path), 'detail_sha256': sha(H / '四时段已核验逐笔.csv'),
           'code_sha256': sha(Path(__file__)), 'note': 'Descriptive equal-notional sample, not independent or an account.'}
    (H / '四时段合并独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_COMBINED_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
