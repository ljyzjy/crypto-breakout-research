"""Verify that only coherent zero-trade hours can be reconstructed."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import verify_zero_hours as check

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    x = pd.DataFrame([{'open': 100., 'high': 101., 'low': 99., 'close': 100., 'volume': 1., 'quote_volume': 100., 'trade_count': 1.} for _ in range(60)])
    x.loc[5] = {'open': 100., 'high': 100., 'low': 100., 'close': 100., 'volume': 0., 'quote_volume': 0., 'trade_count': 0.}
    official = {'open': 100., 'high': 101., 'low': 99., 'close': 100., 'volume': 59., 'quote_volume': 5900., 'count': 59.}
    good = check.inspect(x, official); assert good['status'] == 'verified_zero_minutes' and good['zero_trade_minutes'] == 1
    broken = x.copy(); broken.loc[5, 'volume'] = 1.
    assert check.inspect(broken, official)['status'] == 'unknown_zero_minute_semantics'
    mismatch = {**official, 'close': 100.2}
    assert check.inspect(x, mismatch)['status'] == 'unknown_hour_disagreement'
    assert check.inspect(x.iloc[:-1], official)['status'] == 'unknown_minute_count'
    assert check.inspect(x, None)['status'] == 'unknown_hour_archive_or_row'
    result = {'all_checks_pass': True, 'checks': ['valid_zero_minute', 'contradictory_volume', 'hourly_mismatch', 'missing_minute', 'missing_hour'],
              'code_sha256': sha(Path(__file__)), 'engine_sha256': sha(H / 'verify_zero_hours.py')}
    (H / '零成交小时合成核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_SYNTHETIC_PASS', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
