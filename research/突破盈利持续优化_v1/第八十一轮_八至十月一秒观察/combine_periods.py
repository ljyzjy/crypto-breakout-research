"""Describe four unequal historical windows as equal-notional unit opportunities."""
import csv
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics

getcontext().prec = 40
D = Decimal


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((H / '八至十月汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '八至十月一秒观察结果.json')
    prior = P / '第七十三轮_二零二三扩展核验'
    prior_audit = json.loads((prior / '三时段合并独立核验.json').read_text(encoding='utf-8'))
    assert prior_audit['all_checks_pass'] and prior_audit['result_sha256'] == sha(prior / '三时段合并单位机会.json')
    fixed = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    ledgers = []
    for year in ('2023', '2024', '2026'):
        folder = prior / '2023持仓量冻结结果' if year == '2023' else P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
        manifest = folder / '冻结哈希.json'
        assert sha(manifest) == fixed['oi_snapshots'][year]
        name = f'{year}一秒观察持仓量逐笔.csv'
        meta = json.loads(manifest.read_text(encoding='utf-8'))
        assert sha(folder / name) == meta['files'][name]
        with (folder / name).open(encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                ledgers.append({'period': year, 'observation_id': row['observation_id'], 'variant': row['variant'],
                                'entry_ts': int(row['entry_ts']), 'net': D(row['net'])})
    with (H / '八至十月候选状态与账本.csv').open(encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            if row['category'] == 'trade':
                ledgers.append({'period': '2026_aug_oct', 'observation_id': row['observation_id'],
                                'variant': f"one_observation_2r_{row['leverage']}x",
                                'entry_ts': int(row['entry_ts']), 'net': D(row['net'])})
    assert len({(x['observation_id'], x['variant']) for x in ledgers}) == len(ledgers)
    rows = []
    previous = json.loads((prior / '三时段合并单位机会.json').read_text(encoding='utf-8'))
    new = json.loads((H / '八至十月一秒观察结果.json').read_text(encoding='utf-8'))
    for lev in (10, 20):
        all_ = [x for x in ledgers if x['variant'].endswith(f'_{lev}x')]
        old = [x for x in all_ if x['period'] != '2026_aug_oct']
        new_ = [x for x in all_ if x['period'] == '2026_aug_oct']
        a = next(x for x in previous['rows'] if x['leverage'] == lev and x['cohort'] == 'base')
        b = next(x for x in new['rows'] if x['leverage'] == lev and x['exit_slippage_pct'] == .05)
        assert len(old) == a['known_trades'] and len(new_) == b['known_trades']
        for records, baseline in ((old, a), (new_, b)):
            m = metrics(records, baseline['unknown_candidates'])
            assert m['net_wins'] == baseline['net_wins']
            assert abs(m['mean_net_pct_notional'] - baseline['mean_net_pct_notional']) < 1e-10
        rows.append({'leverage': lev, **metrics(all_, a['unknown_candidates'] + b['unknown_candidates']),
                     'candidate_events': 361, 'known_no_order': 361 - len(all_) - a['unknown_candidates'] - b['unknown_candidates']})
    out_file = H / '四时段已核验逐笔.csv'
    with out_file.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['period', 'observation_id', 'variant', 'entry_ts', 'net'])
        writer.writeheader(); writer.writerows(ledgers)
    out = {'rows': rows, 'detail_sha256': sha(out_file), 'previous_summary_sha256': sha(prior / '三时段合并单位机会.json'),
           'previous_audit_sha256': sha(prior / '三时段合并独立核验.json'),
           'current_summary_sha256': sha(H / '八至十月一秒观察结果.json'),
           'current_audit_sha256': sha(H / '八至十月汇总独立核验.json'),
           'code_sha256': sha(Path(__file__)),
           'note': 'Unequal historical windows, equal-notional unit returns only; 42 unknown preserved, not blind or account results.'}
    (H / '四时段等名义合并.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_COMBINED', json.dumps(rows, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
