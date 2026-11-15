"""Build verified ex-post 1 ATR candle labels for chronological training only."""
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
R77 = P / '第七十七轮_滚动事前模型'
sys.path.insert(0, str(R95)); import run_expanded_walkforward as prior
M = 60000


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def datasets():
    frozen77 = json.loads((R77 / '冻结时点.json').read_text(encoding='utf-8'))
    out = {'2022': prior.custom_load('2022'), '2026_aug_oct': prior.custom_load('2026_aug_oct')}
    for period in ('2023', '2024', '2026'): out[period], _ = prior.old.load(period, frozen77)
    return out


def verify_daily_sample(symbol, day, q, normalized):
    name = f'{symbol}-1m-{day}.zip'
    url = f'https://data.binance.vision/data/futures/um/daily/klines/{symbol}/1m/{name}'
    c = requests.get(url + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
    bits = c.text.strip().split(); assert len(bits) >= 2 and Path(bits[1]).name == name
    response = requests.get(url, timeout=(15, 90)); response.raise_for_status(); body = response.content
    assert hashlib.sha256(body).hexdigest() == bits[0].lower()
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        assert len(z.namelist()) == 1
        first = z.open(z.namelist()[0]).readline().decode('utf-8-sig').strip()
    header = first.lower().startswith('open_time,')
    frame = pd.read_csv(io.BytesIO(body), compression='zip', header=0 if header else None,
                        names=None if header else prior.guard.minutes.COLS)
    frame = frame[['open_time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'count']].apply(pd.to_numeric, errors='raise')
    assert not frame.open_time.duplicated().any()
    frame = frame.set_index('open_time'); a = normalized.reindex(range(q, q + 900000, M))
    b = frame.reindex(range(q, q + 900000, M)).rename(columns={'count': 'trade_count'})
    cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']
    left, right = a[cols].to_numpy(float), b[cols].to_numpy(float)
    assert len(a) == len(b) == 15 and np.isfinite(left).all() and np.isfinite(right).all()
    assert np.allclose(left, right, rtol=1e-9, atol=1e-10)
    return {'symbol': symbol, 'day': day, 'quarter_start': q, 'sha256': bits[0].lower(), 'rows_checked': 15}


def main():
    prior.guard.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and frozen['prior_outcomes_and_labels_seen']
    for name, path in frozen['source_paths'].items(): assert sha(Path(path)) == frozen['source_sha256'][name]
    for path in (R95 / '扩充滚动模型独立核验.json', R92 / '突破柱分解独立核验.json',
                 R45 / '2023大柱捕捉独立核验.json', R53 / '跨期大柱捕捉独立核验.json', R63 / '延伸候选独立核验总表.json'):
        assert json.loads(path.read_text(encoding='utf-8'))['all_checks_pass']
    data = datasets()
    unique = {}
    for period, rows in data.items():
        for row in rows:
            key = period, row['observation_id']
            if key in unique:
                assert int(unique[key]['signal']['decision_ts']) == int(row['signal']['decision_ts'])
                assert int(unique[key]['signal']['side']) == int(row['signal']['side'])
            else: unique[key] = row
    early22 = pd.read_csv(R92 / '突破柱逐笔分解.csv', dtype=str, keep_default_na=False)
    early22 = early22[early22.holding_rule.eq('original')]
    labels22 = {(x['observation_id'], int(x['leverage'])): x for x in early22.to_dict('records')}
    l23 = pd.read_parquet(R45 / '2023候选事后大柱标签.parquet').set_index('observation_id').to_dict('index')
    lold = pd.read_parquet(R53 / '跨期事后大柱标签.parquet').set_index(['source_year', 'observation_id']).to_dict('index')
    manifest = json.loads((R63 / '行情代码冻结哈希.json').read_text(encoding='utf-8'))['source']
    late = [(key, row) for key, row in unique.items() if key[0] == '2026_aug_oct']
    grouped = {}
    for key, row in late: grouped.setdefault(row['signal']['contract'], []).append((key, row))
    late_labels, frames = {}, {}
    for sym, records in sorted(grouped.items()):
        prior.guard.guard()
        src = manifest[sym]; assert sha(Path(src['path'])) == src['sha256']
        frame = pd.read_parquet(src['path'], columns=['ts', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']).set_index('ts')
        assert frame.index.is_unique; frames[sym] = src['path']
        for key, r in records:
            s = r['signal']; q = int(s['quarter_start']); chunk = frame.reindex(range(q, q + 900000, M))
            cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']
            a = chunk[cols].to_numpy(float); valid = len(chunk) == 15 and np.isfinite(a).all() and (a > 0).all()
            late_labels[key] = {'status': 'verified' if valid else 'unknown_bar', 'open': float(chunk.open.iloc[0]) if valid else None,
                                'close': float(chunk.close.iloc[-1]) if valid else None, 'source': 'frozen_2026_aug_oct_minutes'}
        del frame
    selected = sorted((key, row) for key, row in late if late_labels[key]['status'] == 'verified')
    picks = sorted(set([0, len(selected)//2, len(selected)-1])) if selected else []
    samples = []
    for i in picks:
        key, row = selected[i]; s = row['signal']; q = int(s['quarter_start'])
        day = pd.Timestamp(q, unit='ms', tz='UTC').strftime('%Y-%m-%d')
        frame = pd.read_parquet(frames[s['contract']], columns=['ts', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']).set_index('ts')
        samples.append(verify_daily_sample(s['contract'], day, q, frame)); del frame
    output = []
    for (period, obs), row in sorted(unique.items()):
        s = row['signal']; side = int(s['side']); q, end, atr = int(s['quarter_start']), int(s['quarter_end']), float(s['atr'])
        assert side in (-1, 1) and end == q + 900000 and atr > 0 and q <= int(s['decision_ts']) < end
        if period == '2022':
            lev = int(row['variant'].rsplit('_', 1)[1].rstrip('x')); x = labels22[(obs, lev)]
            status = x['status']; op = float(x['quarter_open']) if status == 'verified' else None
            close = float(x['quarter_close']) if status == 'verified' else None; source = 'audited_2022_bar'
        elif period == '2023':
            x = l23[obs]; status = x['status']; op = float(x['open']) if status == 'verified' else None
            close = float(x['close']) if status == 'verified' else None; source = 'audited_2023_bar'
            if status == 'verified': assert int(x['allowed_side']) == side and int(x['quarter_start']) == q
        elif period in ('2024', '2026'):
            x = lold[(period, obs)]; status = x['status']; op = float(x['open']) if status == 'verified' else None
            close = float(x['close']) if status == 'verified' else None; source = 'audited_2024_2026_bar'
            if status == 'verified': assert int(x['allowed_side']) == side and int(x['quarter_start']) == q
        else:
            x = late_labels[(period, obs)]; status, op, close, source = x['status'], x['open'], x['close'], x['source']
        valid = status == 'verified' and np.isfinite([op, close, atr]).all() and min(op, close, atr) > 0
        output.append({'period': period, 'observation_id': obs, 'contract': s['contract'], 'quarter_start': q, 'label_available_ts': end,
                       'side': side, 'atr': atr, 'bar_open': op, 'bar_close': close, 'status': 'verified' if valid else 'unknown_bar',
                       'big_aligned': bool(side * (close - op) >= atr) if valid else None, 'source': source})
    labels = pd.DataFrame(output); assert not labels.duplicated(['period', 'observation_id']).any()
    labels.to_parquet(H / '事后大柱训练标签.parquet', index=False)
    summary = {'period_counts': {str(k): int(v) for k, v in labels.groupby('period').size().to_dict().items()},
               'status_counts': labels.status.value_counts().to_dict(), 'verified_big_count': int(labels.big_aligned.eq(True).sum()),
               'late_official_daily_samples': samples, 'label_sha256': sha(H / '事后大柱训练标签.parquet'),
               'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
               'note': 'Labels require completed candle and are for prior training and ex-post scoring only.'}
    (H / '事后大柱标签质量.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT96_LABELS', json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
