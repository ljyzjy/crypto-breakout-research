"""Cross-check zero-trade minutes against official hourly archives, preserving original files."""
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import zipfile

import numpy as np
import pandas as pd
import requests

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
M, HOUR = 60000, 3600000


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def monthly_hour(symbol, month):
    folder = runner.ROOT / 'zero_hour_official_1h' / symbol
    folder.mkdir(parents=True, exist_ok=True)
    name = f'{symbol}-1h-{month}.zip'; dest = folder / name
    url = f'https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/1h/{name}'
    check = requests.get(url + '.CHECKSUM', timeout=(15, 50)); check.raise_for_status()
    fields = check.text.strip().split(); assert len(fields) >= 2 and Path(fields[1]).name == name and len(fields[0]) == 64
    digest = fields[0].lower()
    if not dest.exists():
        tmp = dest.with_suffix('.zip.partial'); hasher = hashlib.sha256(); size = 0
        with requests.get(url, stream=True, timeout=(15, 90)) as r:
            r.raise_for_status()
            with tmp.open('wb') as f:
                for block in r.iter_content(65536):
                    runner.guard(); size += len(block); assert size <= 10_000_000
                    f.write(block); hasher.update(block)
        assert hasher.hexdigest() == digest
        tmp.replace(dest)
    assert sha(dest) == digest
    with zipfile.ZipFile(dest) as z:
        members = z.namelist(); assert len(members) == 1 and members[0].endswith('.csv')
        first = z.open(members[0]).readline().decode('utf-8-sig').strip()
    header = first.lower().startswith('open_time,')
    data = pd.read_csv(dest, compression='zip', header=0 if header else None,
                       names=None if header else runner.minutes.COLS)
    cols = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'count']
    data = data[cols].apply(pd.to_numeric, errors='raise')
    assert not data.open_time.duplicated().any() and (data.open_time % HOUR == 0).all()
    dates = pd.to_datetime(data.open_time, unit='ms', utc=True).dt.strftime('%Y-%m')
    assert dates.eq(month).all() and np.isfinite(data.to_numpy(float)).all()
    return data.set_index('open_time'), {'symbol': symbol, 'month': month, 'url': url, 'sha256': digest,
                                         'path': str(dest), 'bytes': dest.stat().st_size}


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-8)


def inspect(minute, official):
    cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']
    if len(minute) != 60: return {'status': 'unknown_minute_count'}
    x = minute[cols].to_numpy(float)
    if not np.isfinite(x).all(): return {'status': 'unknown_nonfinite'}
    o, h, l, c, volume, quote, count = x.T
    price_ok = (x[:, :4] > 0).all(axis=1) & (h >= np.maximum.reduce([o, l, c])) & (l <= np.minimum.reduce([o, h, c]))
    zeros = (count == 0) & (volume == 0) & (quote == 0) & (o == h) & (o == l) & (o == c)
    active = (count > 0) & (volume > 0) & (quote > 0)
    if not price_ok.all() or not (zeros | active).all() or not zeros.any(): return {'status': 'unknown_zero_minute_semantics'}
    reconstructed = {'open': o[0], 'high': h.max(), 'low': l.min(), 'close': c[-1],
                     'volume': volume.sum(), 'quote_volume': quote.sum(), 'count': count.sum()}
    if any(reconstructed[k] <= 0 for k in ('volume', 'quote_volume', 'count')): return {'status': 'unknown_zero_hour_total'}
    if official is None: return {'status': 'unknown_hour_archive_or_row'}
    differences = {k: float(reconstructed[k]) - float(official[k]) for k in reconstructed}
    if any(not close(reconstructed[k], official[k]) for k in reconstructed if k != 'count') or int(reconstructed['count']) != int(official['count']):
        return {'status': 'unknown_hour_disagreement', 'differences': differences}
    return {'status': 'verified_zero_minutes', 'zero_trade_minutes': int(zeros.sum()),
            'close': float(c[-1]), 'quote_volume': float(quote.sum()), 'differences': differences}


def main():
    runner.guard(start=True)
    test = json.loads((H / '零成交小时合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['engine_sha256'] == sha(Path(__file__)) and test['code_sha256'] == sha(H / 'test_zero_hour.py')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and not frozen['2022_pnl_viewed_before_freeze']
    for k, p in frozen['source_paths'].items(): assert sha(Path(p)) == frozen['source_sha256'][k]
    diagnosis = json.loads((R90 / '未知排名小时来源诊断.json').read_text(encoding='utf-8'))
    assert diagnosis['all_checks_pass'] and diagnosis['code_sha256'] == sha(R90 / 'diagnose_unknown_hours.py')
    supplement = json.loads((R90 / '二零二二日档补源质量.json').read_text(encoding='utf-8'))
    sources = {x['symbol']: x for x in supplement['selected_sources']}
    root = runner.ROOT / 'zero_hour_repaired_features'; root.mkdir(parents=True, exist_ok=True)
    hour_tasks = {}
    for x in diagnosis['invalid_hour_inputs']:
        mon = pd.Timestamp(x['open_time_ms'], unit='ms', tz='UTC').strftime('%Y-%m')
        hour_tasks.setdefault((x['symbol'], mon), []).append(x)
    hourly, archive_meta, archive_errors = {}, [], []
    for symbol, month in sorted(hour_tasks):
        runner.guard()
        try:
            hourly[(symbol, month)], meta = monthly_hour(symbol, month); archive_meta.append(meta)
            print('EXT94_HOUR_SOURCE', len(archive_meta) + len(archive_errors), '/', len(hour_tasks), symbol, month, 'verified', flush=True)
        except Exception as exc:
            archive_errors.append({'symbol': symbol, 'month': month, 'error': type(exc).__name__ + ':' + str(exc)[:160]})
            print('EXT94_HOUR_SOURCE', len(archive_meta) + len(archive_errors), '/', len(hour_tasks), symbol, month, 'unknown', flush=True)
    items, modified_files = [], []
    metas = [json.loads(p.read_text(encoding='utf-8')) for p in (runner.ROOT / 'candidate_chunks').glob('*.json')]
    for item in sorted(metas, key=lambda x: x['symbol']):
        runner.guard()
        symbol = item['symbol']; src = sources[symbol]
        assert sha(Path(src['path'])) == src['sha256'] == item['source_sha256']
        minute = pd.read_parquet(src['path']).set_index('ts')
        hours = pd.read_parquet(item['hours_path']).copy(); before = hours.copy()
        for x in (z for z in diagnosis['invalid_hour_inputs'] if z['symbol'] == symbol):
            ts = int(x['open_time_ms']); mon = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m')
            official = hourly.get((symbol, mon)); row = official.loc[ts] if official is not None and ts in official.index else None
            result = inspect(minute.reindex(range(ts, ts + HOUR, M)), row)
            rec = {'symbol': symbol, 'open_time_ms': ts, 'month': mon, **result}
            items.append(rec)
            match = hours.open_time.eq(ts); assert int(match.sum()) == 1 and not bool(hours.loc[match, 'valid'].iloc[0])
            if result['status'] == 'verified_zero_minutes':
                hours.loc[match, 'close'] = result['close']; hours.loc[match, 'quote_volume'] = result['quote_volume']; hours.loc[match, 'valid'] = True
        other = ~hours.open_time.isin([x['open_time_ms'] for x in items if x['symbol'] == symbol and x['status'] == 'verified_zero_minutes'])
        pd.testing.assert_frame_equal(hours.loc[other].reset_index(drop=True), before.loc[other].reset_index(drop=True), check_exact=True)
        path = root / (symbol + '_hours.parquet'); hours.to_parquet(path, index=False)
        modified_files.append({'symbol': symbol, 'path': str(path), 'sha256': sha(path),
                               'original_hour_path': item['hours_path'], 'original_hour_sha256': sha(Path(item['hours_path']))})
    assert len(items) == len(diagnosis['invalid_hour_inputs'])
    out = {'process_complete': True, 'hour_statuses': dict(Counter(x['status'] for x in items)), 'hours': items,
           'verified_hour_archives': archive_meta, 'archive_errors': archive_errors, 'hourly_sources': modified_files,
           'diagnosis_sha256': sha(R90 / '未知排名小时来源诊断.json'), 'frozen_sha256': sha(H / '冻结时点.json'),
           'code_sha256': sha(Path(__file__)),
           'note': 'Alternative data semantics only; official 1h agreement does not establish exchange service or execution.'}
    (H / '零成交小时来源核对.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT94_HOUR_CHECK', json.dumps({'hour_statuses': out['hour_statuses'], 'archive_errors': len(archive_errors)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
