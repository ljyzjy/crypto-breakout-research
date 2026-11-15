"""Re-download sample tapes and rederive outcomes with a separate scalar implementation."""
import csv
import hashlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
import sys
import zipfile

import pandas as pd
import requests
import replay_2022 as runner

H = Path(__file__).resolve().parent
P = H.parent
R62 = P / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(R62))
import audit_tape_samples as scalar


def load_extended_scalar():
    path = P / '第八十八轮_延长一根柱持有/audit_tape_samples.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('scalar_extended_90', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, path


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def download(sym, archive):
    date = archive['day']
    name = f'{sym}-aggTrades-{date}.zip'
    url = f'https://data.binance.vision/data/futures/um/daily/aggTrades/{sym}/{name}'
    folder = runner.ROOT / 'independent_audit_raw'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    assert target.resolve().is_relative_to(runner.ROOT.resolve())
    check = requests.get(url + '.CHECKSUM', timeout=(15, 50)); check.raise_for_status()
    pieces = check.text.strip().split()
    assert len(pieces) >= 2 and Path(pieces[1]).name == name and pieces[0].lower() == archive['sha256']
    if target.exists():
        assert sha(target) == archive['sha256']
    else:
        partial = target.with_suffix('.zip.partial')
        digest = hashlib.sha256(); size = 0
        with requests.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            with partial.open('wb') as f:
                for chunk in response.iter_content(256 * 1024):
                    runner.guard()
                    size += len(chunk)
                    assert size <= 400_000_000
                    f.write(chunk); digest.update(chunk)
        assert digest.hexdigest() == archive['sha256'] and size == archive['bytes']
        partial.replace(target)
    assert target.stat().st_size == archive['bytes']
    return target


def scalar_parse(path, lo, hi):
    found = []
    with zipfile.ZipFile(path) as z:
        members = z.namelist(); assert len(members) == 1 and members[0].endswith('.csv')
        with io.TextIOWrapper(z.open(members[0]), encoding='utf-8-sig', newline='') as f:
            rows = csv.reader(f)
            first = next(rows)
            if first[0].strip().lower() == 'agg_trade_id':
                index = {k: first.index(k) for k in ('agg_trade_id', 'price', 'quantity', 'transact_time', 'is_buyer_maker')}
            else:
                assert len(first) == 7
                index = {'agg_trade_id': 0, 'price': 1, 'quantity': 2, 'transact_time': 5, 'is_buyer_maker': 6}
                rows = itertools.chain([first], rows)
            for i, row in enumerate(rows):
                if i % 200000 == 0: runner.guard()
                t = int(row[index['transact_time']])
                if lo <= t < hi:
                    maker = row[index['is_buyer_maker']].strip().lower()
                    assert maker in ('true', 'false')
                    found.append((int(row[index['agg_trade_id']]), float(row[index['price']]),
                                  float(row[index['quantity']]), t, maker))
                    assert len(found) <= 500000
    return pd.DataFrame(found, columns=['agg_trade_id', 'price', 'quantity', 'transact_time', 'is_buyer_maker'])


def independent_bars(body, date):
    rows = []
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert len(z.namelist()) == 1
        with io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig', newline='') as f:
            it = csv.reader(f); first = next(it)
            if first[0].lower() == 'open_time':
                index = {k: first.index(k) for k in ('open_time', 'open', 'high', 'low', 'close')}
            else:
                assert len(first) == 12
                index = {'open_time': 0, 'open': 1, 'high': 2, 'low': 3, 'close': 4}
                it = itertools.chain([first], it)
            for row in it:
                rows.append((int(row[index['open_time']]), *[float(row[index[k]]) for k in ('open', 'high', 'low', 'close')]))
    d = pd.DataFrame(rows, columns=['open_time', 'open', 'high', 'low', 'close']).set_index('open_time')
    lo = int(pd.Timestamp(date, tz='UTC').timestamp() * 1000)
    assert d.index.is_unique and all(lo <= int(t) < lo + 86400000 for t in d.index)
    return d


def main():
    runner.guard(start=True)
    proof = json.loads((R62 / '独立重放合成核验.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['audit_code_sha256'] == sha(R62 / 'audit_tape_samples.py')
    assert proof['decision_code_sha256'] == sha(R62 / 'one_second_observation.py')
    candidates = pd.read_parquet(H / '候选数据/固定十一币双币过滤潜在触价.parquet')
    fp = runner.fingerprint()
    progress = json.loads((H / '一秒逐笔回放进度.json').read_text(encoding='utf-8'))
    assert progress['fingerprint'] == fp
    known = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}
    available = []
    for (sym, day), group in candidates.groupby(['contract', 'day'], sort=True):
        events = group.to_dict('records')
        p = runner.WORK / (runner.key(fp, sym, day, events) + '.json')
        if not p.exists(): continue
        cp = json.loads(p.read_text(encoding='utf-8'))
        assert cp['fingerprint'] == fp and cp['status'] == 'verified'
        by = {r['observation_id']: r for r in cp['rows']}
        for e in events:
            r = by[e['observation_id']]
            if r['status'] in known: available.append((e, cp, r))
    available.sort(key=lambda x: (sum(a.get('bytes', 0) for a in x[1]['archives'] if a['kind'] == 'aggTrades'), x[0]['observation_id']))
    chosen, ids = [], set()
    def choose(predicate):
        hit = next((v for v in available if v[0]['observation_id'] not in ids and predicate(v)), None)
        if hit: chosen.append(hit); ids.add(hit[0]['observation_id'])
    for status in ('qualified', 'flow_filter_not_met', 'known_risk_rejected', 'first_direction_ineligible'):
        choose(lambda x, status=status: x[2]['status'] == status)
    choose(lambda x: any(p.get('reason') == 'quarter_time' and p.get('status') == 'verified' for p in x[2].get('paths', {}).values()))
    for cohort in ('opening', 'touch'):
        if len(chosen) < 6: choose(lambda x, cohort=cohort: x[0]['cohort'] == cohort)
    assert len(chosen) >= 3
    extended, ext_path = load_extended_scalar()
    samples = []
    for e, cp, row in chosen:
        runner.guard()
        obs = e['observation_id']
        body, meta = runner.minutes.archive('klines', e['contract'], e['day'])
        assert meta['sha256'] == next(x['sha256'] for x in cp['archives'] if x['kind'] == 'klines')
        bars = independent_bars(body, e['day']); del body
        frames, tape_archives = [], []
        for archive in (x for x in cp['archives'] if x['kind'] == 'aggTrades'):
            local = download(e['contract'], archive)
            frame = scalar_parse(local, int(e['trigger_minute']), int(e['quarter_end']) + 900000 + 60000)
            if len(frame): frames.append(frame)
            tape_archives.append({'day': archive['day'], 'sha256': archive['sha256'], 'bytes': archive['bytes']})
        assert frames
        tape = pd.concat(frames, ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
        original_checked = scalar.replay(e, tape, bars, row)
        extended_checked = 0
        for variant, old in row.get('paths', {}).items():
            new = row.get('extended_paths', {}).get(variant, {})
            if old.get('status') == 'verified' and old.get('reason') == 'quarter_time' and new.get('status') == 'verified':
                extended.scalar_extended({**old, 'side': row['side'], 'quarter_end': e['quarter_end']}, tape, new)
                extended_checked += 1
            elif old.get('status') == 'verified' and old.get('reason') != 'quarter_time':
                assert old == new
        samples.append({'observation_id': obs, 'status': row['status'], 'original_paths_checked': original_checked,
                        'extended_paths_checked': extended_checked, 'minute_sha256': meta['sha256'], 'tape_archives': tape_archives})
        print('EXT90_SAMPLE', len(samples), '/', len(chosen), flush=True)
    output = {'all_checks_pass': True, 'samples': samples, 'batch_fingerprint': fp,
              'original_scalar_sha256': sha(R62 / 'audit_tape_samples.py'), 'extended_scalar_sha256': sha(ext_path),
              'code_sha256': sha(Path(__file__)), 'note': 'Independent CSV reader and scalar replay on selected samples; public prints are not actual fills.'}
    (H / '一秒逐笔独立样本核验.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_SAMPLE_PASS', len(samples), flush=True)


if __name__ == '__main__':
    main()
