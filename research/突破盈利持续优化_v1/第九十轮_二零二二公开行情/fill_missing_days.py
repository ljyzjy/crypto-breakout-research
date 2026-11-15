"""Repair only frozen missing dates using individually verified daily archives."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd
import requests

import acquire_klines as data

H = Path(__file__).resolve().parent
SYMS = ('SOLUSDT', 'XRPUSDT', 'LTCUSDT', 'NEARUSDT')
GAPS = ('2022-02-26', '2022-02-27', '2022-02-28', '2022-04-01', '2022-04-02')
OVERLAPS = ('2022-02-25', '2022-03-01', '2022-03-31', '2022-04-03')


def fetch(root, sym, day):
    name = f'{sym}-1m-{day}.zip'
    url = f'https://data.binance.vision/data/futures/um/daily/klines/{sym}/1m/{name}'
    folder = root / 'raw_daily' / sym; folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    assert target.resolve().is_relative_to(root.resolve())
    error = ''
    for attempt in range(3):
        try:
            data.guard(root)
            with requests.Session() as s:
                c = s.get(url + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
                parts = c.text.split()
                assert len(parts) >= 2 and re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]) and Path(parts[1]).name == name
                expected = parts[0].lower()
                if target.exists():
                    if data.sha(target) != expected: raise ValueError('existing_archive_sha_changed')
                else:
                    partial = target.with_suffix('.zip.partial')
                    digest, size = hashlib.sha256(), 0
                    with s.get(url, stream=True, timeout=(15, 90)) as r:
                        r.raise_for_status()
                        with partial.open('wb') as out:
                            for chunk in r.iter_content(65536):
                                data.guard(root); size += len(chunk)
                                if size > 2_000_000: raise ValueError('archive_stream_cap')
                                digest.update(chunk); out.write(chunk)
                    if digest.hexdigest() != expected: raise ValueError('checksum_mismatch')
                    partial.replace(target)
            frame, _ = data.read_month(target, sym, day[:7])
            lo = int(pd.Timestamp(day, tz='UTC').timestamp() * 1000)
            assert len(frame) == 1440 and np.array_equal(frame.ts.to_numpy(dtype=np.int64), np.arange(lo, lo + 86400000, 60000, dtype=np.int64))
            return {'symbol': sym, 'day': day, 'status': 'verified', 'path': str(target), 'sha256': expected, 'bytes': target.stat().st_size}
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)[:160]
            if any(x in error for x in ('headroom', '404', 'stream_cap', 'existing_archive_sha_changed')): break
            if attempt < 2: time.sleep(attempt + 1)
    return {'symbol': sym, 'day': day, 'status': 'unknown', 'error': error}


def main():
    frozen = json.loads((H / '日档补源规则冻结.json').read_text(encoding='utf-8'))
    assert frozen['original_freeze_sha256'] == data.sha(H / '冻结时点.json')
    assert frozen['original_quality_sha256'] == data.sha(H / '二零二二分钟数据质量.json')
    assert frozen['original_archive_manifest_sha256'] == data.sha(H / '月线分钟档案来源.json')
    assert frozen['amendment_sha256'] == data.sha(H / '日档补源规则.md')
    info = json.loads((H / '二零二二分钟数据质量.json').read_text(encoding='utf-8'))
    root = Path(json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))['data_root'])
    data.guard(root, start=True)
    specs = [(s, day) for s in SYMS for day in (*GAPS, *OVERLAPS)]
    rows = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(fetch, root, s, day) for s, day in specs]
        for i, job in enumerate(as_completed(jobs), 1):
            rows.append(job.result())
            if i % 8 == 0 or i == len(jobs):
                print('EXT90_DAILY_SOURCE', i, '/', len(jobs), 'unknown', sum(x['status'] != 'verified' for x in rows), flush=True)
    daymap = {(x['symbol'], x['day']): x for x in rows}
    selected, overlap_checks = [], []
    for source in info['normalized']:
        sym = source['symbol']; original = Path(source['path'])
        assert data.sha(original) == source['sha256']
        if sym not in SYMS:
            selected.append(source); continue
        data.guard(root)
        base = pd.read_parquet(original)
        relevant = [daymap[(sym, day)] for day in (*GAPS, *OVERLAPS)]
        if any(x['status'] != 'verified' for x in relevant):
            selected.append({**source, 'repair_status': 'unknown_daily_source'}); continue
        try:
            for day in OVERLAPS:
                rec = daymap[(sym, day)]; path = Path(rec['path']); assert data.sha(path) == rec['sha256']
                daily, _ = data.read_month(path, sym, day[:7])
                lo = int(pd.Timestamp(day, tz='UTC').timestamp() * 1000)
                existing = base[base.ts.between(lo, lo + 86400000 - 1)].sort_values('ts').reset_index(drop=True)
                assert len(existing) == len(daily) == 1440 and np.array_equal(existing.ts.to_numpy(), daily.ts.to_numpy())
                for col in existing.columns:
                    assert np.allclose(existing[col].to_numpy(), daily[col].to_numpy(), rtol=1e-10, atol=1e-10), (sym, day, col)
                overlap_checks.append({'symbol': sym, 'day': day, 'rows': 1440, 'daily_sha256': rec['sha256']})
            fill = []
            for day in GAPS:
                rec = daymap[(sym, day)]; path = Path(rec['path']); assert data.sha(path) == rec['sha256']
                daily, _ = data.read_month(path, sym, day[:7])
                lo = int(pd.Timestamp(day, tz='UTC').timestamp() * 1000)
                assert not base.ts.between(lo, lo + 86400000 - 1).any()
                fill.append(daily)
            patched = pd.concat([base, *fill], ignore_index=True).sort_values('ts')
            assert len(patched) == len(base) + 7200 and not patched.ts.duplicated().any()
            folder = root / 'normalized_daily_repaired'; folder.mkdir(parents=True, exist_ok=True)
            out = folder / f'{sym}_klines.parquet'
            patched.to_parquet(out, index=False)
            selected.append({**source, 'path': str(out), 'sha256': data.sha(out), 'rows': len(patched),
                             'original_path': str(original), 'original_sha256': source['sha256'],
                             'missing_minutes': source['missing_minutes'] - 7200, 'repair_status': 'verified_daily_gaps'})
            print('EXT90_DAILY_REPAIRED', sym, 'overlap_days', len(OVERLAPS), 'filled_days', len(GAPS), flush=True)
        except Exception as exc:
            selected.append({**source, 'repair_status': 'unknown_disagreement', 'repair_error': type(exc).__name__ + ':' + str(exc)[:160]})
            print('EXT90_DAILY_REPAIR_UNKNOWN', sym, type(exc).__name__, str(exc)[:100], flush=True)
    out = {'selected_sources': selected, 'daily_archives': sorted(rows, key=lambda x: (x['symbol'], x['day'])),
           'overlap_checks': overlap_checks, 'all_daily_repaired': all(x.get('repair_status') == 'verified_daily_gaps' for x in selected if x['symbol'] in SYMS),
           'remaining_missing_minutes': sum(x['missing_minutes'] for x in selected),
           'amendment_sha256': data.sha(H / '日档补源规则冻结.json'), 'original_quality_sha256': data.sha(H / '二零二二分钟数据质量.json'),
           'code_sha256': data.sha(Path(__file__)), 'note': 'Original monthly normalized files preserved; only absent full days can be added.'}
    (H / '二零二二日档补源质量.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_DAILY_COMPLETE', out['all_daily_repaired'], 'remaining_missing_minutes', out['remaining_missing_minutes'], flush=True)


if __name__ == '__main__':
    main()
