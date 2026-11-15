"""Independently check every alternative hourly patch and official archive checksum."""
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys
import zipfile

import pandas as pd
import requests

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-8)


def main():
    runner.guard(start=True)
    path = H / '零成交小时来源核对.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['process_complete'] and result['code_sha256'] == sha(H / 'verify_zero_hours.py')
    assert result['diagnosis_sha256'] == sha(R90 / '未知排名小时来源诊断.json')
    hourly = {}
    for arc in result['verified_hour_archives']:
        runner.guard()
        p = Path(arc['path']); assert p.stat().st_size == arc['bytes'] and sha(p) == arc['sha256']
        response = requests.get(arc['url'] + '.CHECKSUM', timeout=(15, 50)); response.raise_for_status()
        parts = response.text.split(); assert parts[0].lower() == arc['sha256'] and Path(parts[1]).name == p.name
        with zipfile.ZipFile(p) as z:
            first = z.open(z.namelist()[0]).readline().decode('utf-8-sig').strip()
        header = first.lower().startswith('open_time,')
        d = pd.read_csv(p, compression='zip', header=0 if header else None,
                        names=None if header else runner.minutes.COLS, dtype=str)
        assert not d.open_time.duplicated().any()
        hourly[(arc['symbol'], arc['month'])] = {int(r['open_time']): r for r in d.to_dict('records')}
    supplement = json.loads((R90 / '二零二二日档补源质量.json').read_text(encoding='utf-8'))
    sources = {x['symbol']: x for x in supplement['selected_sources']}
    checks, patched = 0, 0
    for source in result['hourly_sources']:
        runner.guard()
        symbol = source['symbol']
        assert sha(Path(source['path'])) == source['sha256'] and sha(Path(source['original_hour_path'])) == source['original_hour_sha256']
        minute_path = Path(sources[symbol]['path']); assert sha(minute_path) == sources[symbol]['sha256']
        m = pd.read_parquet(minute_path).set_index('ts')
        old = pd.read_parquet(source['original_hour_path']).set_index('open_time')
        new = pd.read_parquet(source['path']).set_index('open_time')
        assert old.index.equals(new.index)
        entries = [x for x in result['hours'] if x['symbol'] == symbol]
        accepted = {x['open_time_ms'] for x in entries if x['status'] == 'verified_zero_minutes'}
        pd.testing.assert_frame_equal(old.loc[~old.index.isin(accepted)], new.loc[~new.index.isin(accepted)], check_exact=True)
        for item in entries:
            ts = int(item['open_time_ms']); assert not bool(old.loc[ts, 'valid'])
            if item['status'] != 'verified_zero_minutes':
                assert not bool(new.loc[ts, 'valid']); checks += 1; continue
            hours = m.reindex(range(ts, ts + 3600000, 60000)); assert len(hours) == 60
            values = hours[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']].to_dict('records')
            assert len(values) == 60
            zeros = 0
            for row in values:
                o, h, l, c, v, q, n = (D(str(row[k])) for k in ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count'))
                assert all(x.is_finite() for x in (o, h, l, c, v, q, n)) and min(o, h, l, c) > 0 and h >= max(o, l, c) and l <= min(o, h, c)
                if n == 0:
                    assert v == q == 0 and o == h == l == c; zeros += 1
                else: assert n > 0 and v > 0 and q > 0
            assert zeros == item['zero_trade_minutes'] > 0
            expected = {'open': D(str(values[0]['open'])), 'close': D(str(values[-1]['close'])),
                        'high': max(D(str(x['high'])) for x in values), 'low': min(D(str(x['low'])) for x in values),
                        'volume': sum(D(str(x['volume'])) for x in values),
                        'quote_volume': sum(D(str(x['quote_volume'])) for x in values),
                        'count': sum(D(str(x['trade_count'])) for x in values)}
            original = hourly[(symbol, item['month'])][ts]
            assert all(near(expected[k], original[k]) for k in expected)
            assert bool(new.loc[ts, 'valid']) and near(new.loc[ts, 'close'], expected['close']) and near(new.loc[ts, 'quote_volume'], expected['quote_volume'])
            checks += 1; patched += 1
    assert checks == len(result['hours'])
    out = {'all_checks_pass': True, 'source_archives_checked': len(result['verified_hour_archives']),
           'affected_hours_checked': checks, 'repaired_hours_checked': patched,
           'source_sha256': sha(path), 'code_sha256': sha(Path(__file__)),
           'note': 'Cross-source OHLC and zero-trade semantics; no claim about exchange availability or real fills.'}
    (H / '零成交小时独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_HOUR_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
