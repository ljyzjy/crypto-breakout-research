import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
sys.path.insert(0, str(P / '第六十九轮_一秒观察持仓量门'))
from evaluate_2026_oi_gate import metrics


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((H / '持仓量过滤独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '持仓量过滤对照.json')
    prior = P / '第七十三轮_二零二三扩展核验'
    prior_audit = json.loads((prior / '三时段合并独立核验.json').read_text(encoding='utf-8'))
    assert prior_audit['all_checks_pass'] and prior_audit['result_sha256'] == sha(prior / '三时段合并单位机会.json')
    hashes = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    detail = []
    for year in ('2023', '2024', '2026'):
        folder = prior / '2023持仓量冻结结果' if year == '2023' else P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
        manifest = folder / '冻结哈希.json'
        assert sha(manifest) == hashes['oi_snapshots'][year]
        name = f'{year}一秒观察持仓量逐笔.csv'
        assert sha(folder / name) == json.loads(manifest.read_text(encoding='utf-8'))['files'][name]
        with (folder / name).open(encoding='utf-8', newline='') as f:
            for x in csv.DictReader(f):
                if x['gate'] == 'True':
                    detail.append({'period': year, 'observation_id': x['observation_id'], 'variant': x['variant'],
                                   'entry_ts': int(x['entry_ts']), 'net': Decimal(x['net'])})
                else:
                    assert x['gate'] in ('False', '')
    with (H / '持仓量过滤逐笔.csv').open(encoding='utf-8', newline='') as f:
        for x in csv.DictReader(f):
            if x['oi_gate'] == 'True':
                detail.append({'period': '2026_aug_oct', 'observation_id': x['observation_id'],
                               'variant': f"one_observation_2r_{x['leverage']}x", 'entry_ts': int(x['entry_ts']), 'net': Decimal(x['net'])})
            else:
                assert x['oi_gate'] in ('False', '')
    assert len({(x['observation_id'], x['variant']) for x in detail}) == len(detail)
    previous = json.loads((prior / '三时段合并单位机会.json').read_text(encoding='utf-8'))
    current = json.loads((H / '持仓量过滤对照.json').read_text(encoding='utf-8'))
    rows = []
    for lev in (10, 20):
        all_ = [x for x in detail if x['variant'].endswith(f'_{lev}x')]
        old = [x for x in all_ if x['period'] != '2026_aug_oct']
        new = [x for x in all_ if x['period'] == '2026_aug_oct']
        a = next(x for x in previous['rows'] if x['leverage'] == lev and x['cohort'] == 'oi_gate')
        b = next(x for x in current['rows'] if x['leverage'] == lev and x['cohort'] == 'oi_gate' and x['exit_slippage_pct'] == .05)
        for vals, baseline in ((old, a), (new, b)):
            m = metrics(vals, baseline['unknown_candidates'])
            assert m['known_trades'] == baseline['known_trades'] and m['net_wins'] == baseline['net_wins']
            if vals:
                assert abs(m['mean_net_pct_notional'] - baseline['mean_net_pct_notional']) < 1e-10
        unknown = a['unknown_candidates'] + b['unknown_candidates']
        rows.append({'leverage': lev, **metrics(all_, unknown), 'candidate_events': 361,
                     'known_no_order': 361 - len(all_) - unknown})
    path = H / '四时段持仓量已核验逐笔.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['period', 'observation_id', 'variant', 'entry_ts', 'net']); w.writeheader(); w.writerows(detail)
    out = {'rows': rows, 'detail_sha256': sha(path), 'prior_summary_sha256': sha(prior / '三时段合并单位机会.json'),
           'prior_audit_sha256': sha(prior / '三时段合并独立核验.json'), 'current_summary_sha256': sha(H / '持仓量过滤对照.json'),
           'current_audit_sha256': sha(H / '持仓量过滤独立核验.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Different historical window lengths, equal-notional unit paths; no account or independent blind sample.'}
    (H / '四时段持仓量合并.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT82_COMBINED', json.dumps(rows, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
