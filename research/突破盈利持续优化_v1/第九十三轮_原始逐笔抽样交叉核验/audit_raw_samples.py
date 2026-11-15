"""Reread raw and aggregate samples with pandas and recheck official ZIP hashes."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import zipfile

import pandas as pd
import compare_raw_aggregate as compare

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def independent_window(path, kind, lo, hi):
    with zipfile.ZipFile(path) as z:
        assert len(z.namelist()) == 1
        first = z.open(z.namelist()[0]).readline().decode('utf-8-sig').strip().split(',')
    header = first[0].lower() in ('id', 'trade_id', 'agg_trade_id')
    names = (['agg_trade_id', 'price', 'quantity', 'first_trade_id', 'last_trade_id', 'transact_time', 'is_buyer_maker']
             if kind == 'aggTrades' else ['id', 'price', 'qty', 'quote_qty', 'time', 'is_buyer_maker'])
    columns = first if header else names
    idname = 'agg_trade_id' if kind == 'aggTrades' else ('id' if 'id' in columns else 'trade_id')
    qty = 'quantity' if 'quantity' in columns else 'qty'
    time = 'transact_time' if 'transact_time' in columns else 'time'
    wanted = [idname, 'price', qty, time, 'is_buyer_maker']
    parts = []
    for chunk in pd.read_csv(path, compression='zip', header=0 if header else None, names=None if header else names,
                             usecols=wanted, dtype=str, chunksize=120000):
        compare.runner.guard()
        times = pd.to_numeric(chunk[time], errors='raise')
        selected = chunk[(times >= lo) & (times < hi)]
        for x in selected.to_dict('records'):
            maker = x['is_buyer_maker'].strip().lower(); assert maker in ('true', 'false')
            parts.append((int(x[time]), int(x[idname]), Decimal(x['price']), Decimal(x[qty]), maker))
    return sorted(parts, key=lambda r: (r[0], r[1]))


def main():
    compare.runner.guard(start=True)
    source_path = H / '原始聚合逐笔样本对照.json'
    source = json.loads(source_path.read_text(encoding='utf-8'))
    assert source['code_sha256'] == sha(H / 'compare_raw_aggregate.py')
    data = pd.read_parquet(R90 / '候选数据/固定十一币双币过滤潜在触价.parquet')
    by = {}; fp = compare.runner.fingerprint()
    for (sym, day), group in data.groupby(['contract', 'day'], sort=True):
        events = group.to_dict('records')
        path = compare.runner.WORK / (compare.runner.key(fp, sym, day, events) + '.json')
        if not path.exists(): continue
        cp = json.loads(path.read_text(encoding='utf-8')); assert cp['fingerprint'] == fp
        rows = {x['observation_id']: x for x in cp['rows']}
        for event in events: by[event['observation_id']] = (event, cp, rows[event['observation_id']])
    compare.read_window = independent_window
    checked, skipped = 0, 0
    for sample in source['samples']:
        if sample['status'] == 'unknown':
            skipped += 1; continue
        event, cp, row = by[sample['observation_id']]
        again = compare.compare_sample(event, cp, row)
        assert again == sample, sample['observation_id']
        checked += 1
        print('EXT93_INDEPENDENT_SAMPLE', checked, '/', len(source['samples']), flush=True)
    out = {'all_checks_pass': True, 'samples_checked': checked, 'unknown_samples_skipped': skipped,
           'source_sha256': sha(source_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Independent pandas parsing, fresh official checksums and existing full ZIP hashes; unknown samples stay unknown.'}
    (H / '原始逐笔独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT93_RAW_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
