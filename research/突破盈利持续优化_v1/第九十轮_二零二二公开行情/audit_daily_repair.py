"""Independently audit every repaired or overlap daily source against final minutes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import time
import zipfile

import numpy as np
import pandas as pd
import requests

import acquire_klines as guardlib

H = Path(__file__).resolve().parent
SYMS = ('SOLUSDT', 'XRPUSDT', 'LTCUSDT', 'NEARUSDT')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def checksum(meta, root):
    name = Path(meta['path']).name
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{meta['symbol']}/1m/{name}.CHECKSUM"
    for attempt in range(3):
        try:
            guardlib.guard(root)
            r = requests.get(url, timeout=(15, 50)); r.raise_for_status()
            parts = r.text.split()
            assert parts[0].lower() == meta['sha256'] and Path(parts[1]).name == name
            return meta
        except requests.exceptions.RequestException:
            if attempt == 2: raise
            time.sleep(attempt + 1)


def rows(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist(); assert len(names) == 1
        with io.TextIOWrapper(z.open(names[0]), encoding='utf-8-sig', newline='') as file:
            reader = csv.reader(file)
            first = next(reader)
            if first[0].lower() == 'open_time':
                headers = first
            else:
                headers = guardlib.COLS
                yield dict(zip(headers, first))
            for row in reader:
                yield dict(zip(headers, row))


def main():
    source_path = H / '二零二二日档补源质量.json'
    source = json.loads(source_path.read_text(encoding='utf-8'))
    frozen = json.loads((H / '日档补源规则冻结.json').read_text(encoding='utf-8'))
    assert source['amendment_sha256'] == sha(H / '日档补源规则冻结.json')
    assert source['original_quality_sha256'] == sha(H / '二零二二分钟数据质量.json')
    assert source['code_sha256'] == sha(H / 'fill_missing_days.py')
    assert frozen['amendment_sha256'] == sha(H / '日档补源规则.md')
    assert source['all_daily_repaired'] and source['remaining_missing_minutes'] == 0
    root = Path(json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))['data_root'])
    guardlib.guard(root, start=True)
    archives = source['daily_archives']
    assert len(archives) == 36 and all(x['status'] == 'verified' for x in archives)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(checksum, x, root) for x in archives]
        for i, job in enumerate(as_completed(jobs), 1):
            job.result()
            if i % 9 == 0 or i == len(jobs): print('EXT90_DAILY_AUDIT_CHECKSUM', i, '/', len(jobs), flush=True)
    selected = {x['symbol']: x for x in source['selected_sources']}
    checks = 0
    for sym in SYMS:
        meta = selected[sym]
        assert sha(Path(meta['path'])) == meta['sha256'] and sha(Path(meta['original_path'])) == meta['original_sha256']
        before = pd.read_parquet(meta['original_path']).sort_values('ts').reset_index(drop=True)
        after = pd.read_parquet(meta['path']).sort_values('ts').reset_index(drop=True)
        ids = np.searchsorted(after.ts.to_numpy(dtype=np.int64), before.ts.to_numpy(dtype=np.int64))
        assert len(after) == len(before) + 7200 and np.array_equal(after.ts.to_numpy()[ids], before.ts.to_numpy())
        for col in before.columns:
            assert np.array_equal(after[col].to_numpy()[ids], before[col].to_numpy())
        indexed = after.set_index('ts')
        for archive in (x for x in archives if x['symbol'] == sym):
            path = Path(archive['path']); assert sha(path) == archive['sha256']
            start = int(pd.Timestamp(archive['day'], tz='UTC').timestamp() * 1000)
            count = 0
            for row in rows(path):
                ts = int(row['open_time'])
                assert ts == start + count * 60000 and int(row['close_time']) == ts + 59999 and ts in indexed.index
                target = indexed.loc[ts]
                for source_name, target_name in [('open','open'), ('high','high'), ('low','low'), ('close','close'),
                                                  ('volume','volume'), ('quote_volume','quote_volume'),
                                                  ('count','trade_count'), ('taker_buy_quote_volume','taker_buy_quote_volume')]:
                    assert math.isclose(float(row[source_name]), float(target[target_name]), rel_tol=1e-10, abs_tol=1e-10)
                count += 1
            assert count == 1440
            checks += 1
        print('EXT90_DAILY_AUDIT_SYMBOL', sym, 'original_rows', len(before), flush=True)
    assert checks == 36
    out = {'all_checks_pass': True, 'daily_archives_checked': checks, 'daily_minute_rows_checked': checks * 1440,
           'original_rows_preserved_for_symbols': list(SYMS), 'remaining_missing_minutes': source['remaining_missing_minutes'],
           'source_sha256': sha(source_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Daily gaps and overlaps verified; same-exchange historical sources, not live availability.'}
    (H / '日档补源独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_DAILY_AUDIT_PASS', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
