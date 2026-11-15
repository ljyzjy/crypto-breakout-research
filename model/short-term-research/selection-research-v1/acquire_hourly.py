"""Hourly spot signals for the historical daily-qualified union; no return screening."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import io
import zipfile
import pandas as pd
import selection_engine as e
from acquire_data import cached_listing, fetch

ROOT = e.ROOT


def main():
    rows = e.old.prior.slow_rankings()
    symbols = sorted({'BTCUSDT', 'ETHUSDT'} | {p['symbol'] for r in rows
        if '2025-01-01' <= r['date'] <= '2026-04-26' for p in r['pool']})
    old_records = {x['key']: x for x in e.old.manifest()['archives'] if x['key'].startswith('data/spot/')}
    keys = []
    def discover(s):
        return [k for k in cached_listing(f'data/spot/monthly/klines/{s}/1h/')
                if k.endswith('.zip') and '2024-09' <= k[-11:-4] <= '2026-04']
    with ThreadPoolExecutor(max_workers=8) as pool:
        for k in pool.map(discover, symbols):
            keys.extend(k)
    e.base.dump(ROOT/'hourly-plan.json', {'symbols': symbols, 'keys': sorted(keys)})
    print('Hourly plan', len(symbols), 'assets', len(keys), 'archives', flush=True)
    def archive(key):
        previous = old_records.get(key)
        path = ROOT.parent/previous['file'] if previous else ROOT/'hourly-archives'/key.split('/')[-1]
        check = path.with_suffix('.sha256')
        expected = previous['sha256'] if previous else (check.read_text().strip() if check.exists()
            else fetch('https://data.binance.vision/'+key+'.CHECKSUM').decode().split()[0])
        blob = path.read_bytes() if path.exists() else fetch('https://data.binance.vision/'+key)
        sha = hashlib.sha256(blob).hexdigest()
        assert sha == expected
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            check.write_text(sha)
        return {'key':key, 'path':str(path.relative_to(ROOT.parent)), 'sha256':sha}
    records = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, f in enumerate(as_completed([pool.submit(archive, k) for k in keys]), 1):
            records.append(f.result())
            if i % 100 == 0 or i == len(keys):
                print('Hourly verified', i, '/', len(keys), flush=True)
    manifest = {'archives':sorted(records,key=lambda r:r['key']), 'processed':{}, 'internal_gaps':{}}
    for s in symbols:
        chunks = []
        for r in records:
            if r['key'].split('/')[4] != s:
                continue
            with zipfile.ZipFile(ROOT.parent/r['path']) as z:
                d = pd.read_csv(z.open(z.namelist()[0]), header=None)
            d = d.iloc[:,[0,1,2,3,4,5,7]]
            d.columns = ['date','open','high','low','close','volume','quote_volume']
            d.date = pd.to_datetime(d.date.where(d.date < 10**14, d.date//1000), unit='ms', utc=True)
            chunks.append(d)
        if not chunks:
            continue
        d = pd.concat(chunks).drop_duplicates().sort_values('date').set_index('date')
        assert not d.index.duplicated().any(), s
        gaps = pd.date_range(d.index.min(),d.index.max(),freq='h').difference(d.index)
        manifest['internal_gaps'][s] = [t.isoformat() for t in gaps]
        path = ROOT/'hourly-data'/f'{s}.parquet'
        path.parent.mkdir(parents=True,exist_ok=True)
        d.to_parquet(path)
        manifest['processed'][s] = {'path':str(path.relative_to(ROOT.parent)),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rows':len(d)}
    e.base.dump(ROOT/'hourly-manifest.json',manifest)
    print('Hourly panel ready; missing bars',sum(map(len,manifest['internal_gaps'].values())),flush=True)


if __name__ == '__main__':
    main()
