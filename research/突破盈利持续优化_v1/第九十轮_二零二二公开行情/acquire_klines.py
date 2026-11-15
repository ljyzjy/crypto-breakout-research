"""Acquire and normalize checksum-verified monthly 2022 public minutes to D:."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import threading
import time
import zipfile

import numpy as np
import pandas as pd
import psutil
import requests

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT', 'ADAUSDT', 'LINKUSDT', 'AVAXUSDT', 'LTCUSDT', 'NEARUSDT']
MONTHS = ['2021-12'] + [f'2022-{i:02d}' for i in range(1, 13)]
COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']
LOCAL = threading.local()


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def guard(data_root, start=False):
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError('system_disk_headroom')
    if shutil.disk_usage(data_root).free < 5_000_000_000:
        raise RuntimeError('data_disk_headroom')
    if psutil.virtual_memory().available < (850 if start else 300) * 1024**2:
        raise RuntimeError('memory_headroom')


def session():
    if not hasattr(LOCAL, 'session'):
        LOCAL.session = requests.Session()
    return LOCAL.session


def fetch(data_root, spec):
    sym, month = spec
    name = f'{sym}-1m-{month}.zip'
    url = f'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1m/{name}'
    folder = data_root / 'raw' / sym
    folder.mkdir(parents=True, exist_ok=True)
    target, meta = folder / name, folder / (name + '.json')
    assert target.resolve().is_relative_to(data_root.resolve())
    error = ''
    for attempt in range(3):
        try:
            guard(data_root)
            response = session().get(url + '.CHECKSUM', timeout=(15, 50)); response.raise_for_status()
            parts = response.text.split()
            assert len(parts) >= 2 and re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]) and Path(parts[1]).name == name
            expected = parts[0].lower()
            if target.exists():
                if sha(target) != expected:
                    raise ValueError('existing_archive_sha_changed')
            else:
                partial = target.with_suffix('.zip.partial')
                digest, size = hashlib.sha256(), 0
                with session().get(url, stream=True, timeout=(15, 120)) as r:
                    r.raise_for_status()
                    with partial.open('wb') as stream:
                        for chunk in r.iter_content(262144):
                            guard(data_root)
                            size += len(chunk)
                            if size > 50_000_000:
                                raise ValueError('archive_stream_cap')
                            digest.update(chunk); stream.write(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError('checksum_mismatch')
                partial.replace(target)
            record = {'symbol': sym, 'month': month, 'status': 'verified', 'url': url,
                      'sha256': expected, 'bytes': target.stat().st_size, 'path': str(target)}
            meta.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            return record
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)[:160]
            if any(word in error for word in ('headroom', '404', 'archive_stream_cap', 'existing_archive_sha_changed')):
                break
            if attempt < 2:
                time.sleep(attempt + 1)
    return {'symbol': sym, 'month': month, 'status': 'unknown', 'error': error, 'url': url}


def read_month(path, sym, month):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0] == path.name.replace('.zip', '.csv')
        with z.open(names[0]) as f:
            first = f.readline().decode('utf-8-sig').lower()
        header = first.startswith('open_time,')
    frame = pd.read_csv(path, compression='zip', header=0 if header else None, names=None if header else COLS)
    assert set(COLS[:11]).issubset(frame.columns)
    required = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'count', 'taker_buy_quote_volume']
    frame = frame[required].apply(pd.to_numeric, errors='raise').sort_values('open_time')
    lo = int(pd.Timestamp(month + '-01', tz='UTC').timestamp() * 1000)
    hi = int((pd.Timestamp(month + '-01', tz='UTC') + pd.offsets.MonthBegin(1)).timestamp() * 1000)
    times = frame.open_time.to_numpy(dtype=np.int64)
    assert not frame.open_time.duplicated().any() and ((times % 60000) == 0).all()
    assert frame.open_time.between(lo, hi - 1).all() and (frame.close_time.to_numpy(dtype=np.int64) == times + 59999).all()
    values = frame[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'count', 'taker_buy_quote_volume']].to_numpy(float)
    assert np.isfinite(values).all() and (values[:, :4] > 0).all() and (values[:, 4:] >= 0).all()
    assert (values[:, 1] >= np.max(values[:, [0, 2, 3]], axis=1)).all()
    assert (values[:, 2] <= np.min(values[:, [0, 1, 3]], axis=1)).all()
    assert (frame['count'] == frame['count'].astype('int64')).all()
    expected = (hi - lo) // 60000
    data = frame.drop(columns=['close_time']).rename(columns={'open_time': 'ts', 'count': 'trade_count'})
    data = data[['ts', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count', 'taker_buy_quote_volume']]
    data['ts'] = data.ts.astype('int64'); data['trade_count'] = data.trade_count.astype('int64')
    return data, {'month': month, 'rows': len(data), 'expected_minutes': expected, 'missing_minutes': expected - len(data)}


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, path in frozen['source_paths'].items():
        assert sha(Path(path)) == frozen['source_sha256'][name]
    root = Path(frozen['data_root'])
    root.mkdir(parents=True, exist_ok=True)
    guard(root, start=True)
    specs = [(sym, mon) for sym in SYMBOLS for mon in MONTHS]
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(fetch, root, spec) for spec in specs]
        for i, job in enumerate(as_completed(jobs), 1):
            result = job.result(); results.append(result)
            if i % 10 == 0 or i == len(jobs):
                print('EXT90_DOWNLOAD', i, '/', len(jobs), 'unknown', sum(x['status'] != 'verified' for x in results), flush=True)
    manifest = {'sources': sorted(results, key=lambda x: (x['symbol'], x['month'])), 'total': len(specs),
                'verified': sum(x['status'] == 'verified' for x in results), 'frozen_sha256': sha(H / '冻结时点.json'),
                'code_sha256': sha(Path(__file__))}
    (H / '月线分钟档案来源.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    lookup = {(x['symbol'], x['month']): x for x in results}
    normalized = []
    for sym in SYMBOLS:
        guard(root)
        archives = [lookup[(sym, mon)] for mon in MONTHS]
        if any(x['status'] != 'verified' for x in archives):
            normalized.append({'symbol': sym, 'status': 'unknown_missing_archive'})
            continue
        pieces, quality = [], []
        try:
            for x in archives:
                guard(root)
                path = Path(x['path']); assert sha(path) == x['sha256']
                frame, stats = read_month(path, sym, x['month']); pieces.append(frame); quality.append(stats)
            frame = pd.concat(pieces, ignore_index=True).sort_values('ts')
            assert not frame.ts.duplicated().any() and frame.ts.is_monotonic_increasing
            folder = root / 'normalized'; folder.mkdir(parents=True, exist_ok=True)
            out = folder / f'{sym}_klines.parquet'
            frame.to_parquet(out, index=False)
            normalized.append({'symbol': sym, 'status': 'verified', 'path': str(out), 'sha256': sha(out),
                               'rows': len(frame), 'missing_minutes': sum(x['missing_minutes'] for x in quality), 'months': quality})
            print('EXT90_NORMALIZED', len(normalized), '/11', sym, 'missing_minutes', normalized[-1]['missing_minutes'], flush=True)
        except Exception as exc:
            normalized.append({'symbol': sym, 'status': 'unknown_normalization', 'error': type(exc).__name__ + ':' + str(exc)[:180]})
            print('EXT90_NORMALIZE_UNKNOWN', sym, type(exc).__name__, str(exc)[:100], flush=True)
    result = {'source_manifest_sha256': sha(H / '月线分钟档案来源.json'), 'normalized': normalized,
              'all_symbols_verified': len(normalized) == len(SYMBOLS) and all(x['status'] == 'verified' for x in normalized),
              'total_missing_minutes': sum(x.get('missing_minutes', 0) for x in normalized),
              'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
              'note': 'Missing minutes are not interpolated; candidate and rank audits are still outstanding.'}
    (H / '二零二二分钟数据质量.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_DATA_COMPLETE', result['all_symbols_verified'], 'missing_minutes', result['total_missing_minutes'], flush=True)


if __name__ == '__main__':
    main()
