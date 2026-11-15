"""Preserve the raw-vs-aggregate path discrepancy; do not select either path."""
import hashlib
import io
import json
from pathlib import Path

import pandas as pd

import reconcile_three as rec

H = Path(__file__).resolve().parent
OBS = 'opening|SOLUSDT|1787819400000'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    result = json.loads((H / '三个候选来源复核.json').read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'reconcile_three.py')
    item = next(x for x in result['candidates'] if x['observation_id'] == OBS)
    assert item['status'] == 'unknown_path_disagreement'
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    source = rec.runner.OLD / '候选数据/固定十一币双币过滤潜在触价.parquet'
    assert sha(source) == frozen['candidate_sha256']
    candidates = pd.read_parquet(source).set_index('observation_id')
    e = candidates.loc[OBS].to_dict(); e['observation_id'] = OBS
    sym, day, start = e['contract'], e['day'], int(e['trigger_minute'])
    archived = {a['kind']: a for a in item['archives']}
    body, _ = rec.fetch('klines', sym, day, archived['klines'])
    allbars = pd.read_csv(io.BytesIO(body), compression='zip', dtype=str); del body
    bar = allbars[allbars.open_time.astype('int64').eq(start)].iloc[0]
    body, _ = rec.fetch('aggTrades', sym, day, archived['aggTrades'])
    agg = rec.window(body, 'aggTrades', start, int(e['quarter_end']) + 60000); del body
    body, _ = rec.fetch('trades', sym, day, archived['trades'])
    raw = rec.window(body, 'trades', start, int(e['quarter_end']) + 60000); del body
    am = [x for x in agg if x[0] < start + 60000]
    av = rec.ohlc(am)
    def frame(rows):
        return pd.DataFrame([{'transact_time': x[0], 'agg_trade_id': x[1], 'price': float(x[2]),
                              'quantity': float(x[3]), 'is_buyer_maker': x[4]} for x in rows])
    def bars(ohlc):
        return pd.DataFrame([dict(zip(('open', 'high', 'low', 'close'), map(float, ohlc)))], index=[start])
    official = [rec.D(bar[k]) for k in ('open', 'high', 'low', 'close')]
    aggregate = rec.runner.engine.decide(e, frame(agg), bars(av))
    raw_result = rec.runner.engine.decide(e, frame(raw), bars(official))
    assert aggregate['paths'] == item['aggregate_paths']
    diffs = {}
    for variant in sorted(set(aggregate.get('paths', {})) | set(raw_result.get('paths', {}))):
        a, b = aggregate.get('paths', {}).get(variant, {}), raw_result.get('paths', {}).get(variant, {})
        diffs[variant] = {key: {'aggregate': a.get(key), 'raw': b.get(key)}
                          for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)}
    out = {'observation_id': OBS, 'aggregate_status': aggregate['status'], 'raw_status': raw_result['status'],
           'aggregate_paths': aggregate.get('paths', {}), 'raw_paths': raw_result.get('paths', {}),
           'path_differences': diffs, 'prior_result_sha256': sha(H / '三个候选来源复核.json'),
           'code_sha256': sha(Path(__file__)),
           'note': 'Diagnostic same-exchange archive difference; no path selected and event remains unknown.'}
    (H / 'SOL路径分歧诊断.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT83_SOL_DISAGREEMENT', json.dumps(diffs, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
