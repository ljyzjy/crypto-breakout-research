"""Independently check ex-post candle labels and re-fetch late official samples."""
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import pandas as pd
import requests

H = Path(__file__).resolve().parent
P = H.parent
R95 = P / '第九十五轮_扩充训练滚动预测'
R92 = P / '第九十二轮_突破柱收益分解'
R45 = P / '第四十五轮_2023大突破柱捕捉诊断'
R53 = P / '第五十三轮_跨期大柱捕捉诊断'
R63 = P / '第六十三轮_2026八至十月延伸'
sys.path.insert(0, str(R95)); import run_expanded_walkforward as prior
import prepare_big_labels as maker
D = Decimal


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def close(a, b):
    return abs(D(str(a)) - D(str(b))) <= D('1e-10') * max(D(1), abs(D(str(a))), abs(D(str(b))))


def official_sample(item, frame):
    sym, day, q = item['symbol'], item['day'], int(item['quarter_start'])
    name = f'{sym}-1m-{day}.zip'; url = f'https://data.binance.vision/data/futures/um/daily/klines/{sym}/1m/{name}'
    c = requests.get(url + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status(); parts = c.text.strip().split()
    assert parts[0].lower() == item['sha256'] and Path(parts[1]).name == name
    r = requests.get(url, timeout=(15, 90)); r.raise_for_status(); assert hashlib.sha256(r.content).hexdigest() == item['sha256']
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert len(z.namelist()) == 1
        with io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f); first = next(reader)
            names = first if first[0].lower() == 'open_time' else prior.guard.minutes.COLS
            if first[0].lower() != 'open_time': reader = __import__('itertools').chain([first], reader)
            idx = {k: names.index(k) for k in ('open_time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'count')}
            rows = {int(x[idx['open_time']]): x for x in reader if q <= int(x[idx['open_time']]) < q + 900000}
    assert len(rows) == 15
    for ts in range(q, q + 900000, 60000):
        a, b = frame.loc[ts], rows[ts]
        for local, official in [('open','open'), ('high','high'), ('low','low'), ('close','close'), ('volume','volume'), ('quote_volume','quote_volume'), ('trade_count','count')]:
            assert close(a[local], b[idx[official]])


def main():
    prior.guard.guard(start=True)
    quality_path = H / '事后大柱标签质量.json'; quality = json.loads(quality_path.read_text(encoding='utf-8'))
    label_path = H / '事后大柱训练标签.parquet'
    assert quality['label_sha256'] == sha(label_path) and quality['code_sha256'] == sha(H / 'prepare_big_labels.py')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for k, p in frozen['source_paths'].items(): assert sha(Path(p)) == frozen['source_sha256'][k]
    data = maker.datasets(); unique = {}
    for period, rows in data.items():
        for row in rows: unique.setdefault((period, row['observation_id']), row)
    labels = pd.read_parquet(label_path); assert set(zip(labels.period, labels.observation_id)) == set(unique)
    data22 = pd.read_csv(R92 / '突破柱逐笔分解.csv', dtype=str, keep_default_na=False)
    data22 = data22[data22.holding_rule.eq('original')]
    x22 = {(r['observation_id'], int(r['leverage'])): r for r in data22.to_dict('records')}
    x23 = pd.read_parquet(R45 / '2023候选事后大柱标签.parquet').set_index('observation_id').to_dict('index')
    xold = pd.read_parquet(R53 / '跨期事后大柱标签.parquet').set_index(['source_year', 'observation_id']).to_dict('index')
    manifest = json.loads((R63 / '行情代码冻结哈希.json').read_text(encoding='utf-8'))['source']
    late = labels[labels.period.eq('2026_aug_oct')]
    for symbol, group in late.groupby('contract'):
        prior.guard.guard()
        info = manifest[symbol]; assert sha(Path(info['path'])) == info['sha256']
        frame = pd.read_parquet(info['path']).set_index('ts')
        for label in group.to_dict('records'):
            q = int(label['quarter_start']); z = frame.reindex(range(q, q + 900000, 60000))
            a = z[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']].to_numpy(float)
            valid = len(z) == 15 and np.isfinite(a).all() and (a > 0).all()
            assert label['status'] == ('verified' if valid else 'unknown_bar')
            if valid: assert close(label['bar_open'], z.open.iloc[0]) and close(label['bar_close'], z.close.iloc[-1])
        for item in quality['late_official_daily_samples']:
            if item['symbol'] == symbol: official_sample(item, frame)
        del frame
    for z in labels.to_dict('records'):
        period, obs = z['period'], z['observation_id']; r = unique[(period, obs)]; s = r['signal']
        assert int(z['quarter_start']) == int(s['quarter_start']) and int(z['label_available_ts']) == int(s['quarter_end'])
        assert int(z['side']) == int(s['side']) and close(z['atr'], s['atr'])
        if period == '2022':
            lev = int(r['variant'].rsplit('_', 1)[1].rstrip('x')); source = x22[(obs, lev)]
            if z['status'] == 'verified': assert source['status'] == 'verified' and close(z['bar_open'], source['quarter_open']) and close(z['bar_close'], source['quarter_close'])
        elif period == '2023':
            source = x23[obs]
            if z['status'] == 'verified': assert source['status'] == 'verified' and close(z['bar_open'], source['open']) and close(z['bar_close'], source['close'])
        elif period in ('2024', '2026'):
            source = xold[(period, obs)]
            if z['status'] == 'verified': assert source['status'] == 'verified' and close(z['bar_open'], source['open']) and close(z['bar_close'], source['close'])
        if z['status'] == 'verified':
            expected = D(int(z['side'])) * (D(str(z['bar_close'])) - D(str(z['bar_open']))) >= D(str(z['atr']))
            assert bool(z['big_aligned']) == expected
    assert len(quality['late_official_daily_samples']) == min(3, len(late))
    out = {'all_checks_pass': True, 'labels_checked': len(labels), 'verified_labels': int(labels.status.eq('verified').sum()),
           'late_daily_archives_redownloaded': len(quality['late_official_daily_samples']),
           'source_sha256': sha(quality_path), 'label_sha256': sha(label_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Completed candle labels only; future bar information is never a current entry input.'}
    (H / '事后大柱标签独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT96_LABEL_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
