"""Independently re-download and check all risk sources and settled ledger rows."""
import io
from pathlib import Path
import zipfile

import pandas as pd
import replay_2022 as runner

H = Path(__file__).resolve().parent
SOURCE = H.parent / '第八十一轮_八至十月一秒观察/audit_risk.py'


def independent_read(body, kind):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].endswith('.csv')
        first = z.open(names[0]).readline().decode('utf-8-sig').strip()
    names = (['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume',
              'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore'] if kind == 'markPriceKlines'
             else ['calc_time', 'funding_interval_hours', 'last_funding_rate'])
    has_header = first.lower().startswith(names[0] + ',')
    return pd.read_csv(io.BytesIO(body), compression='zip', header=0 if has_header else None,
                       names=None if has_header else names)


def main():
    text = SOURCE.read_text(encoding='utf-8')
    changes = [
        ('import run_replay as runner', 'import replay_2022 as runner'),
        ("assert source['code_sha256'] == sha(H / 'settle_risk.py')", "assert source['code_sha256'] == sha(H / 'settle_risk_2022.py')"),
        ("frame = pd.read_csv(io.BytesIO(body), compression='zip')", 'frame = independent_read(body, kind)'),
    ]
    for old, new in changes:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    env = {'__name__': 'ext90_independent_risk_audit', '__file__': str(Path(__file__)), 'independent_read': independent_read}
    exec(compile(text, str(SOURCE), 'exec'), env)
    env['H'], env['B'] = H, H / '一秒回放批次'
    env['main']()


if __name__ == '__main__':
    main()
