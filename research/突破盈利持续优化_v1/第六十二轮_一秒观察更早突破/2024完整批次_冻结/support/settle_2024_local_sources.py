"""Settle 2024 paths with original risk engine and checked local public ZIPs."""
import hashlib
import importlib.util
import io
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import run_observation as runner

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
OUT = H / '2024一秒观察分批'
JOURNAL = H / '2024本地风险来源记录.jsonl'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source(kind, contract, month):
    if kind == 'markPriceKlines':
        name = f'{contract}-1m-{month}.zip'
        base = Path(r'D:\CodexResearch_2024_mark_571e490ad9c146329044a750196f552f')
    else:
        name = f'{contract}-fundingRate-{month}.zip'
        base = ROOT / 'work/breakout_2024_11/raw/fundingRate'
    return base / contract / name


def append(record):
    with JOURNAL.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def extract_local(kind, contract, month, times, path, digest_source):
    d = pd.read_csv(path, compression='zip')
    cols = ['open_time', 'open', 'high', 'low', 'close'] if kind == 'markPriceKlines' else ['calc_time', 'funding_interval_hours', 'last_funding_rate']
    assert set(cols).issubset(d.columns)
    d = d[cols].apply(pd.to_numeric, errors='raise').rename(columns={'open_time': 'ts', 'calc_time': 'ts'})
    assert np.isfinite(d.to_numpy(float)).all() and not d.ts.duplicated().any()
    lo = int(pd.Timestamp(month + '-01', tz='UTC').timestamp() * 1000)
    hi = int((pd.Timestamp(month + '-01', tz='UTC') + pd.offsets.MonthBegin(1)).timestamp() * 1000)
    assert d.ts.between(lo, hi - 1).all()
    if kind == 'markPriceKlines':
        assert (d.ts % 60000 == 0).all() and (d[['open', 'high', 'low', 'close']] > 0).all().all()
        assert not (d.high < d[['open', 'low', 'close']].max(axis=1)).any()
        assert not (d.low > d[['open', 'high', 'close']].min(axis=1)).any()
        d = d[d.ts.isin(times)]
    else:
        assert (d.funding_interval_hours > 0).all()
    return {'kind': kind, 'contract': contract, 'month': month, 'status': 'verified', 'sha256': digest_source,
            'bytes': path.stat().st_size, 'rows': d.to_dict('records')}


def main():
    runner.inputs('2024')
    test = json.loads((H / '2024本地风险读取对照核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['settlement_code_sha256'] == sha(Path(__file__))
    assert test['plan_sha256'] == sha(H / '2024本地风险结算方案.md')
    assert test['test_code_sha256'] == sha(H / 'test_2024_local_sources.py')
    assert all(sha(Path(path)) == digest for path, digest in test['trusted_manifest_sha256'].items())
    engine_path = P / '第四十四轮_双币过滤跨时段复核/settle_cross_engine.py'
    spec = importlib.util.spec_from_file_location('obs62local2024', engine_path)
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    spec.loader.exec_module(engine)
    original = (P / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy = engine_path.read_text(encoding='utf-8').replace('max_workers=1', 'max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('CROSS44_RISK_COMPLETE'")]
    old_task = engine.task
    engine.HERE = OUT
    engine.WORK = ROOT / 'work/point_in_time_universe33/risk_fixed11_cross46'
    engine.WORK.mkdir(parents=True, exist_ok=True)
    before = ['动态池逐笔信号筛查.parquet', '动态池延迟市价路径.parquet', '动态池逐笔提取质量.json', '逐笔执行冻结方案.json']
    hashes = {name: sha(OUT / name) for name in before}
    (OUT / '风险输入哈希.json').write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')

    def local_task(z):
        kind, contract, month, times = z
        while psutil.virtual_memory().available < 500 * 1024 ** 2:
            if shutil.disk_usage(ROOT).free < 2_200_000_000:
                return {'kind': kind, 'contract': contract, 'month': month, 'status': 'error', 'error': 'disk_headroom', 'rows': []}
            time.sleep(3)
        if shutil.disk_usage(ROOT).free < 2_200_000_000:
            return {'kind': kind, 'contract': contract, 'month': month, 'status': 'error', 'error': 'disk_headroom', 'rows': []}
        digest = hashlib.sha256((engine.FINGERPRINT + '|' + kind + '|' + contract + '|' + month + '|' + ','.join(map(str, times))).encode()).hexdigest()
        cache = engine.WORK / (digest + '.json')
        if cache.exists():
            return json.loads(cache.read_text(encoding='utf-8'))
        path = source(kind, contract, month)
        if not path.is_file():
            return old_task(z)
        name = path.name
        sub = f'{kind}/{contract}/1m/' if kind == 'markPriceKlines' else f'{kind}/{contract}/'
        url = engine.BASE + sub + name + '.CHECKSUM'
        try:
            response = engine.session().get(url, timeout=(15, 50))
            response.raise_for_status()
            parts = response.text.strip().split()
            assert len(parts) >= 2 and re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]) and Path(parts[1]).name == name
            digest_source = sha(path)
            assert digest_source == parts[0].lower()
            out = extract_local(kind, contract, month, times, path, digest_source)
            if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 250 * 1024 ** 2:
                raise RuntimeError('resource_headroom')
            tmp = cache.with_suffix('.partial')
            tmp.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            tmp.replace(cache)
            append({'kind': kind, 'contract': contract, 'month': month, 'source': str(path), 'source_sha256': digest_source,
                    'checksum_url': url, 'cache': str(cache), 'cache_sha256': sha(cache), 'requested_minutes': len(times)})
            return out
        except Exception as exc:
            if 'headroom' in str(exc):
                return {'kind': kind, 'contract': contract, 'month': month, 'status': 'error', 'error': str(exc), 'rows': []}
            append({'kind': kind, 'contract': contract, 'month': month, 'local_fallback': type(exc).__name__ + ':' + str(exc)[:120]})
            return old_task(z)

    engine.task = local_task
    print('OBS62_2024_LOCAL_RISK_BEGIN', flush=True)
    engine.main()
    assert all(sha(OUT / name) == value for name, value in hashes.items())
    print('OBS62_2024_LOCAL_RISK_END', flush=True)


if __name__ == '__main__':
    main()
