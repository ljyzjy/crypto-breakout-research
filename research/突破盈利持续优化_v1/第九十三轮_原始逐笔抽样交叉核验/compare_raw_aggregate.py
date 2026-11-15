"""Compare precommitted 2022 aggregate-trade samples with raw official trades."""
from collections import Counter
import csv
from decimal import Decimal, getcontext
import hashlib
import io
import itertools
import json
from pathlib import Path
import sys
import zipfile

import pandas as pd
import requests

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
D = Decimal
getcontext().prec = 40


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def download_raw(symbol, day):
    name = f'{symbol}-trades-{day}.zip'
    url = f'https://data.binance.vision/data/futures/um/daily/trades/{symbol}/{name}'
    folder = runner.ROOT / 'independent_raw_trade_samples'
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    assert dest.resolve().is_relative_to(runner.ROOT.resolve())
    c = requests.get(url + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
    fields = c.text.strip().split()
    assert len(fields) >= 2 and Path(fields[1]).name == name and len(fields[0]) == 64
    expected = fields[0].lower()
    if dest.exists():
        assert sha(dest) == expected
    else:
        partial = dest.with_suffix('.zip.partial'); digest = hashlib.sha256(); size = 0
        with requests.get(url, stream=True, timeout=(15, 120)) as r:
            r.raise_for_status()
            with partial.open('wb') as f:
                for chunk in r.iter_content(256 * 1024):
                    runner.guard(); size += len(chunk)
                    assert size <= 400_000_000
                    f.write(chunk); digest.update(chunk)
        assert digest.hexdigest() == expected
        partial.replace(dest)
    return dest, {'day': day, 'sha256': expected, 'bytes': dest.stat().st_size, 'url': url}


def read_window(path, kind, lo, hi):
    rows = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist(); assert len(names) == 1 and names[0].endswith('.csv')
        with io.TextIOWrapper(z.open(names[0]), encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f); first = next(reader)
            if first[0].strip().lower() in ('id', 'trade_id', 'agg_trade_id'):
                cols = {k: i for i, k in enumerate(first)}
                ident = cols.get('agg_trade_id') if kind == 'aggTrades' else cols.get('id', cols.get('trade_id'))
                indexes = {'id': ident, 'price': cols['price'],
                           'qty': cols.get('quantity', cols.get('qty')),
                           'time': cols.get('transact_time', cols.get('time')), 'maker': cols['is_buyer_maker']}
                assert all(v is not None for v in indexes.values())
            else:
                assert len(first) == (7 if kind == 'aggTrades' else 6)
                indexes = {'id': 0, 'price': 1, 'qty': 2, 'time': 5 if kind == 'aggTrades' else 4,
                           'maker': 6 if kind == 'aggTrades' else 5}
                reader = itertools.chain([first], reader)
            for i, row in enumerate(reader):
                if i % 200000 == 0: runner.guard()
                ts = int(row[indexes['time']])
                if lo <= ts < hi:
                    maker = row[indexes['maker']].strip().lower(); assert maker in ('true', 'false')
                    rows.append((ts, int(row[indexes['id']]), D(row[indexes['price']]), D(row[indexes['qty']]), maker))
                    assert len(rows) <= 1_000_000
    return sorted(rows, key=lambda x: (x[0], x[1]))


def first_cross(rows, minute, upper, lower):
    hit = next((r for r in rows if minute <= r[0] < minute + 60000 and (r[2] > upper or r[2] < lower)), None)
    return None if hit is None else {'ts': hit[0], 'price': str(hit[2].normalize()), 'side': 1 if hit[2] > upper else -1}


def amounts(rows, ts):
    window = [r for r in rows if ts < r[0] < ts + 1000]
    return {'buy': str(sum((r[2] * r[3] for r in window if r[4] == 'false'), D(0))),
            'sell': str(sum((r[2] * r[3] for r in window if r[4] == 'true'), D(0))),
            'records': len(window)}


def first_after(rows, threshold):
    r = next((r for r in rows if r[0] >= threshold), None)
    return None if r is None else {'ts': r[0], 'price': str(r[2].normalize())}


def compare_sample(event, cp, row):
    minute, decision = int(event['trigger_minute']), int(row['decision_ts'])
    entry_times = [int(p['entry_ts']) for p in row.get('paths', {}).values() if p.get('status') == 'verified']
    hi = max(minute + 60000, int(row['entry_exec_ts']) + 3000, max(entry_times, default=decision) + 3000)
    days = pd.date_range(pd.Timestamp(minute, unit='ms', tz='UTC').normalize(), pd.Timestamp(hi - 1, unit='ms', tz='UTC').normalize(), freq='D').strftime('%Y-%m-%d').tolist()
    aggregate, raw, raw_meta = [], [], []
    for date in days:
        prev = next(a for a in cp['archives'] if a['kind'] == 'aggTrades' and a['day'] == date)
        agg_path = runner.ROOT / 'independent_audit_raw' / f"{event['contract']}-aggTrades-{date}.zip"
        assert agg_path.exists() and sha(agg_path) == prev['sha256']
        aggregate.extend(read_window(agg_path, 'aggTrades', minute, hi))
        path, meta = download_raw(event['contract'], date)
        raw.extend(read_window(path, 'trades', minute, hi)); raw_meta.append(meta)
    aggregate.sort(key=lambda r: (r[0], r[1])); raw.sort(key=lambda r: (r[0], r[1]))
    upper, lower = D(str(event['upper'])), D(str(event['lower']))
    ac, rc = first_cross(aggregate, minute, upper, lower), first_cross(raw, minute, upper, lower)
    checks = {'first_cross': ac == rc and ac is not None,
              'stored_first_cross': ac is not None and ac['ts'] == decision and ac['side'] == int(row['side'])
                                    and D(ac['price']) == D(str(row['signal_close']))}
    fields = {'aggregate_first_cross': ac, 'raw_first_cross': rc}
    if checks['first_cross']:
        at, rt = amounts(aggregate, decision), amounts(raw, decision)
        checks['first_second_buy_sell_amount'] = D(at['buy']) == D(rt['buy']) and D(at['sell']) == D(rt['sell'])
        ar, rr = first_after(aggregate, decision + 1000), first_after(raw, decision + 1000)
        checks['one_second_reference'] = ar == rr and ar is not None
        fields.update(aggregate_first_second=at, raw_first_second=rt, aggregate_reference=ar, raw_reference=rr)
        if row['status'] == 'qualified' and checks['one_second_reference']:
            ae, re = first_after(aggregate, ar['ts'] + 1000), first_after(raw, rr['ts'] + 1000)
            checks['delayed_entry_reference'] = ae == re and ae is not None
            fields.update(aggregate_delayed_entry=ae, raw_delayed_entry=re)
    status = 'agree' if checks and all(checks.values()) else 'disagree'
    return {'observation_id': event['observation_id'], 'contract': event['contract'], 'day': event['day'],
            'signal_status': row['status'], 'status': status, 'checks': checks, **fields, 'raw_archives': raw_meta}


def main():
    runner.guard(start=True)
    synthetic = json.loads((H / '无表头合成核验.json').read_text(encoding='utf-8'))
    assert synthetic['all_checks_pass'] and synthetic['code_sha256'] == sha(H / 'test_raw_parser.py')
    assert synthetic['raw_parser_sha256'] == sha(Path(__file__)) and synthetic['independent_parser_sha256'] == sha(H / 'audit_raw_samples.py')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and not frozen['2022_pnl_viewed_before_freeze']
    for k, p in frozen['source_paths'].items(): assert sha(Path(p)) == frozen['source_sha256'][k]
    audit = json.loads((R90 / '一秒逐笔独立样本核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['batch_fingerprint'] == runner.fingerprint()
    selected = [x for x in audit['samples'] if x['status'] in ('qualified', 'flow_filter_not_met', 'known_risk_rejected')][:3]
    assert selected
    data = pd.read_parquet(R90 / '候选数据/固定十一币双币过滤潜在触价.parquet')
    by_event = {}
    for (sym, day), group in data.groupby(['contract', 'day'], sort=True):
        events = group.to_dict('records')
        path = runner.WORK / (runner.key(runner.fingerprint(), sym, day, events) + '.json')
        if not path.exists(): continue
        cp = json.loads(path.read_text(encoding='utf-8')); assert cp['fingerprint'] == runner.fingerprint()
        by = {r['observation_id']: r for r in cp['rows']}
        for e in events: by_event[e['observation_id']] = (e, cp, by[e['observation_id']])
    output = []
    for sample in selected:
        event, cp, row = by_event[sample['observation_id']]
        try:
            runner.guard()
            result = compare_sample(event, cp, row)
        except Exception as exc:
            result = {'observation_id': event['observation_id'], 'contract': event['contract'], 'day': event['day'],
                      'signal_status': row['status'], 'status': 'unknown', 'error': type(exc).__name__ + ':' + str(exc)[:180]}
        output.append(result)
        print('EXT93_SAMPLE', len(output), '/', len(selected), result['status'], flush=True)
    result = {'samples': output, 'counts': dict(Counter(x['status'] for x in output)),
              'sample_selection_audit_sha256': sha(R90 / '一秒逐笔独立样本核验.json'),
              'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
              'note': 'Only selected raw-vs-aggregate samples; disagreement is unknown, not proof of actual execution.'}
    (H / '原始聚合逐笔样本对照.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT93_COMPLETE', json.dumps(result['counts']), flush=True)


if __name__ == '__main__':
    main()
