"""Supplement only the predeclared selection union using official checked archives."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import io
import json
import zipfile
import psutil
import pandas as pd
import selection_engine as e
from download_pool import fetch, listing

ROOT = e.ROOT
RESEARCH = ROOT.parent


def make_plan():
    rows = e.rankings()
    symbols, plan = set(), set()
    for history in rows.values():
        for row in history:
            if not '2025-01-01' <= row['date'] <= '2026-04-26':
                continue
            for s in row['daily_top2']:
                symbols.add(s)
                for offset in range(-2, 9):
                    d = pd.Timestamp(row['date']) + pd.Timedelta(days=offset)
                    if d <= pd.Timestamp('2026-04-26'):
                        plan.add((s, d.strftime('%Y-%m')))
    for path in sorted((ROOT/'signals').glob('*-hourly.json.gz')):
        daily = {}
        for row in e.base.read(path):
            daily.setdefault(row['date'][:10],set()).update(row['daily_top2'])
        for day, chosen in daily.items():
            for s in chosen:
                symbols.add(s)
                for offset in (-1,0,1):
                    d = pd.Timestamp(day)+pd.Timedelta(days=offset)
                    if d<=pd.Timestamp('2026-04-26'):
                        plan.add((s,d.strftime('%Y-%m')))
    for s in ('BTCUSDT', 'ETHUSDT'):
        symbols.add(s)
        for m in pd.period_range('2024-12', '2026-04', freq='M').astype(str):
            plan.add((s, m))
    e.base.dump(ROOT/'coverage-plan.json', dict(symbols=sorted(symbols), months=sorted(plan)))
    kit = RESEARCH.parent
    saved = json.loads((kit/'user_data/dashboard-processes.local.json').read_text())
    engine = psutil.Process(saved['engine']['pid'])
    assert abs(engine.create_time() - saved['engine']['created']) < .01
    protected = ['config.paper.json', 'config.public-data.json', 'config.dashboard.local.json',
                 'user_data/strategies/DailyCandidates.py', 'user_data/strategies/SpotTrendV1.py']
    if not (ROOT/'paper-before.json').exists():
        e.base.dump(ROOT/'paper-before.json', {'processes': saved, 'hashes': {
            x: hashlib.sha256((kit/x).read_bytes()).hexdigest() for x in protected}})
    print('Planned', len(symbols), 'assets;', len(plan), 'asset-months; paper engine', engine.pid, flush=True)
    return symbols, plan


def cached_listing(prefix, delimiter=None):
    name = hashlib.sha256((prefix + str(delimiter)).encode()).hexdigest() + '.json'
    for p in (ROOT/'listings'/name, e.old.ROOT/'listings'/name):
        if p.exists():
            return e.base.read(p)
    data = listing(prefix, delimiter)
    e.base.dump(ROOT/'listings'/name, data)
    return data


def archive(key):
    path = ROOT/'archives'/key.split('/')[4]/key.split('/')[-1]
    checksum = path.with_suffix('.sha256')
    expected = checksum.read_text().strip() if checksum.exists() else fetch('https://data.binance.vision/'+key+'.CHECKSUM').decode().split()[0]
    blob = path.read_bytes() if path.exists() else fetch('https://data.binance.vision/'+key)
    sha = hashlib.sha256(blob).hexdigest()
    assert sha == expected, key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        checksum.write_text(sha)
    return {'key': key, 'path': str(path.relative_to(RESEARCH)), 'sha256': sha}


def parse(record, kind):
    with zipfile.ZipFile(RESEARCH/record['path']) as z:
        d = pd.read_csv(z.open(z.namelist()[0]))
    if kind == 'fundingRate':
        exact = pd.to_datetime(d.calc_time, unit='ms', utc=True)
        d['date'] = exact.dt.round('h')
        assert (exact-d.date).dt.total_seconds().abs().max() < 60
    else:
        d['date'] = pd.to_datetime(d.open_time, unit='ms', utc=True)
    return d.set_index('date').sort_index()


def main():
    symbols, plan = make_plan()
    oldm = e.old.manifest()
    oldkeys = {r['key'] for r in oldm['archives']}
    contracts = {x.split('/')[-2] for x in cached_listing('data/futures/um/monthly/klines/', '/')}
    mapping = dict(oldm['mapping'])
    for s in sorted(symbols):
        mapping.setdefault(s, next((c for c in (s, '1000'+s, '1000000'+s) if c in contracts), None))
    availability = dict(oldm['availability'])
    jobs = []
    for s in sorted(symbols):
        c = mapping[s]
        if c is None:
            continue
        wanted = {m for a, m in plan if a == s}
        availability.setdefault(s, {})
        for kind in ('klines', 'markPriceKlines', 'fundingRate'):
            prefix = f'data/futures/um/monthly/{kind}/{c}/' + ('' if kind == 'fundingRate' else '5m/')
            keys = [k for k in cached_listing(prefix) if k.endswith('.zip')]
            availability[s][kind] = sorted(k[-11:-4] for k in keys)
            jobs.extend(k for k in keys if k[-11:-4] in wanted and k not in oldkeys)
    jobs = sorted(set(jobs))
    e.base.dump(ROOT/'archive-plan.json', jobs)
    print('Supplemental archive count', len(jobs), flush=True)
    records = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, f in enumerate(as_completed([pool.submit(archive, k) for k in jobs]), 1):
            records.append(f.result())
            if i % 25 == 0 or i == len(jobs):
                print('Verified supplemental archives', i, '/', len(jobs), flush=True)
    manifest = {'mapping': mapping, 'availability': availability, 'processed': {},
                'supplemental_archives': sorted(records, key=lambda r:r['key']),
                'previous_manifest_sha256': hashlib.sha256((e.old.ROOT/'data-manifest.json').read_bytes()).hexdigest(),
                'daily_sha256': hashlib.sha256((e.old.prior.OLD/'pool-daily.parquet').read_bytes()).hexdigest(),
                'overlap_checks': [], 'unavailable_archive_months': []}
    for file, entry in oldm['processed'].items():
        parts = Path(file).parts
        if parts[1] != 'perp':
            continue
        symbol, kind = Path(parts[2]).stem.rsplit('-', 1)
        manifest['processed'][symbol+'/'+kind] = {**entry, 'path': str(Path('rotation-leverage-v1')/file)}
    grouped = {}
    for record in records:
        bits = record['key'].split('/')
        grouped.setdefault((bits[5], bits[4]), []).append(record)
    for (symbol, kind), recs in grouped.items():
        entry = manifest['processed'].get(symbol+'/'+kind)
        prior = pd.read_parquet(RESEARCH/entry['path']) if entry else None
        new = pd.concat([parse(r, kind) for r in recs]).sort_index()
        if prior is not None:
            overlap = prior.index.intersection(new.index)
            if len(overlap):
                pd.testing.assert_frame_equal(prior.loc[overlap], new.loc[overlap], check_dtype=False, check_freq=False)
            manifest['overlap_checks'].append({'symbol': symbol, 'kind': kind, 'identical_rows': len(overlap)})
            new = pd.concat([prior, new.loc[~new.index.isin(prior.index)]]).sort_index()
        assert not new.index.duplicated().any(), (symbol, kind)
        # Missing bars remain missing. Do not fill, invent, or retroactively drop assets.
        path = ROOT/'data'/f'{symbol}-{kind}.parquet'
        path.parent.mkdir(parents=True, exist_ok=True)
        new.to_parquet(path)
        manifest['processed'][symbol+'/'+kind] = {'path': str(path.relative_to(RESEARCH)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'rows': len(new),
            'first': new.index[0].isoformat(), 'last': new.index[-1].isoformat()}
    for s, month in sorted(plan):
        for kind in ('klines', 'markPriceKlines', 'fundingRate'):
            if mapping[s] and month not in availability.get(s, {}).get(kind, []):
                manifest['unavailable_archive_months'].append({'symbol':s,'month':month,'kind':kind})
    e.base.dump(ROOT/'data-manifest.json', manifest)
    print('Data manifest written; missing archive months', len(manifest['unavailable_archive_months']), flush=True)


if __name__ == '__main__':
    main()
