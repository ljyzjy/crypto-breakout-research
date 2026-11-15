"""Independently replay original and streamed 2023 tapes with bounded memory."""
import hashlib, json, shutil, tempfile, time
from pathlib import Path
import numpy as np
import pandas as pd
import psutil
import requests
import extract_old11_tapes as original
import stream_tapes_2023 as streamed
from audit_2023_tape_samples import replay

HERE = Path(__file__).resolve().parent
TMP = original.ROOT / 'work' / 'old11_2023_dual' / 'sample_audit_temp'
MIN_FREE = 2_200_000_000
MIN_MEMORY = 900 * 1024**2
MAX_ARCHIVE = 200_000_000

def main():
    src = pd.read_parquet(original.SOURCE).set_index('observation_id')
    available, seen = [], set()
    for tag, folder in [('original', original.WORK), ('stream', streamed.WORK)]:
        for file in sorted(folder.glob('*.json')):
            rec = json.loads(file.read_text(encoding='utf-8'))
            if rec.get('status') != 'verified':
                continue
            for row in rec['rows']:
                obs = row['observation_id']
                if (obs not in seen and row.get('status') == 'qualified' and row.get('paths')
                    and all(x['status'] == 'verified' for x in row['paths'].values())):
                    assert obs in src.index
                    seen.add(obs)
                    available.append((tag, rec, row))
    selected = []
    def pick(pred):
        for v in available:
            if v not in selected and pred(v):
                selected.append(v)
                return
    # Explicitly exercise the new streamed reader, along with the old path.
    pick(lambda v: v[0] == 'original' and v[2]['side'] == 1)
    pick(lambda v: v[0] == 'original' and v[2]['side'] == -1)
    pick(lambda v: v[0] == 'stream' and any(p.get('reason') == 'target' for p in v[2]['paths'].values()))
    pick(lambda v: v[0] == 'stream' and any(p.get('reason') == 'filled_beyond_risk_budget' for p in v[2]['paths'].values()))
    while len(selected) < 4:
        before = len(selected)
        pick(lambda v: v[0] == 'stream')
        if len(selected) == before:
            raise ValueError('not_enough_independent_stream_samples')
    TMP.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    samples = []
    for tag, rec, row in selected:
        while psutil.virtual_memory().available < MIN_MEMORY:
            time.sleep(3)
            if shutil.disk_usage(original.ROOT).free < MIN_FREE:
                raise RuntimeError('disk_headroom')
        e = {**src.loc[row['observation_id']].to_dict(),
             **{k: v for k, v in row.items() if k not in ('paths', 'prechecks')}}
        blocks = []
        for a in (x for x in rec['archives'] if x['kind'] == 'aggTrades'):
            name = f"{e['contract']}-aggTrades-{a['day']}.zip"
            url = f"https://data.binance.vision/data/futures/um/daily/aggTrades/{e['contract']}/{name}"
            check = s.get(url + '.CHECKSUM', timeout=(15, 50)); check.raise_for_status()
            expected = check.text.strip().split()[0].lower()
            assert expected == a['sha256']
            if shutil.disk_usage(original.ROOT).free < MIN_FREE:
                raise RuntimeError('disk_headroom')
            f = tempfile.NamedTemporaryFile(prefix='audit_', suffix='.zip', dir=TMP, delete=False)
            path = Path(f.name)
            assert path.resolve().parent == TMP.resolve() and not path.is_symlink()
            try:
                sha, size = hashlib.sha256(), 0
                with f:
                    with s.get(url, stream=True, headers={'Accept-Encoding':'identity'}, timeout=(15, 120)) as response:
                        response.raise_for_status()
                        length = response.headers.get('Content-Length')
                        if length is not None and int(length) > MAX_ARCHIVE:
                            raise RuntimeError('archive_exceeds_cap')
                        for b in response.iter_content(chunk_size=1024*1024):
                            if not b: continue
                            size += len(b)
                            if size > MAX_ARCHIVE or shutil.disk_usage(original.ROOT).free - len(b) < MIN_FREE:
                                raise RuntimeError('archive_or_disk_headroom')
                            sha.update(b); f.write(b)
                assert sha.hexdigest() == expected and (length is None or size == int(length))
                cols = ['agg_trade_id', 'price', 'quantity', 'transact_time', 'is_buyer_maker']
                for chunk in pd.read_csv(path, compression='zip', usecols=cols,
                                         dtype={'is_buyer_maker':str}, chunksize=40_000):
                    t = chunk.transact_time.to_numpy(np.int64)
                    z = chunk.loc[(t >= int(e['trigger_minute'])) & (t < int(e['quarter_end']) + 60_000)]
                    if len(z): blocks.append(z)
            finally:
                assert path.resolve().parent == TMP.resolve() and not path.is_symlink()
                if path.exists(): path.unlink()
        tape = pd.concat(blocks, ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
        for variant, expected_path in row['paths'].items():
            lev = int(variant.rsplit('_', 1)[1].rstrip('x'))
            actual = replay(e, tape, lev, variant.startswith('fast_'))
            for key, value in actual.items():
                if isinstance(value, float):
                    assert np.isclose(value, expected_path[key], rtol=1e-11, atol=1e-12), (row['observation_id'], variant, key)
                else:
                    assert value == expected_path[key], (row['observation_id'], variant, key)
        samples.append({'observation_id':row['observation_id'], 'reader':tag, 'side':int(e['side']),
                        'paths_checked':len(row['paths']), 'archives':[x for x in rec['archives'] if x['kind']=='aggTrades']})
        print('OLD11_2023_BOUNDED_SAMPLE', len(samples), '/', len(selected), flush=True)
    out = {'independent_samples':len(samples), 'paths_checked':sum(x['paths_checked'] for x in samples),
           'samples':samples, 'note':'Independent replay of re-downloaded public prints; actual fills remain unknown.'}
    (HERE / '2023逐笔样本独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OLD11_2023_BOUNDED_SAMPLE_PASS', len(samples), flush=True)

if __name__ == '__main__': main()
