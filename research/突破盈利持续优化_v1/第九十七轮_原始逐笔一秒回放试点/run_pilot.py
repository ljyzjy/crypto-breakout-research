"""Replay three previously selected cases using individual public trades."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R90 = P / '第九十轮_二零二二公开行情'
R93 = P / '第九十三轮_原始逐笔抽样交叉核验'
sys.path.insert(0, str(R90)); import replay_2022 as runner
sys.path.insert(0, str(R93)); import compare_raw_aggregate as raw
import settle_risk_2022 as risk2022


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def frozen():
    x = json.loads((H / '研究冻结.json').read_text(encoding='utf-8'))
    for path, digest in x['sources'].items(): assert sha(path) == digest, path
    for arc in x['raw_archives']: assert sha(arc['path']) == arc['sha256'], arc['path']
    return x


def get_inputs():
    candidates = pd.read_parquet(R90 / '候选数据/固定十一币双币过滤潜在触价.parquet')
    selected = set(frozen()['sample_ids']); found = {}
    for (symbol, day), group in candidates.groupby(['contract', 'day'], sort=True):
        if not selected.intersection(group.observation_id): continue
        events = group.to_dict('records')
        fp = runner.fingerprint()
        cp_path = runner.WORK / (runner.key(fp, symbol, day, events) + '.json')
        cp = json.loads(cp_path.read_text(encoding='utf-8'))
        assert cp['status'] == 'verified' and cp['fingerprint'] == fp
        rows = {x['observation_id']: x for x in cp['rows']}
        for e in events:
            if e['observation_id'] in selected: found[e['observation_id']] = (e, cp, rows[e['observation_id']])
    assert set(found) == selected
    return found


def load_case(e, cp, loader=raw.read_window):
    body, bar_meta = runner.minutes.archive('klines', e['contract'], e['day'])
    expected = next(a for a in cp['archives'] if a['kind'] == 'klines' and a['day'] == e['day'])
    assert bar_meta['sha256'] == expected['sha256']
    bars = runner.minute_bars(body, e['day']); del body
    lo, hi = int(e['trigger_minute']), int(e['quarter_end']) + 60000
    dates = pd.date_range(pd.Timestamp(lo, unit='ms', tz='UTC').normalize(),
                          pd.Timestamp(hi-1, unit='ms', tz='UTC').normalize(), freq='D').strftime('%Y-%m-%d')
    rows, archives = [], []
    for date in dates:
        path, meta = raw.download_raw(e['contract'], date)
        rows.extend(loader(path, 'trades', lo, hi)); archives.append(meta)
    rows.sort(key=lambda r: (r[0], r[1]))
    tape = pd.DataFrame([(a, b, float(c), float(d), f) for a,b,c,d,f in rows],
                        columns=['transact_time','agg_trade_id','price','quantity','is_buyer_maker'])
    return tape, bars, bar_meta, archives


def settle_cases(cases):
    paths = []
    for case in cases:
        for variant, path in case['raw_result'].get('paths', {}).items():
            if path['status'] == 'verified':
                paths.append(SimpleNamespace(contract=case['contract'], side=case['raw_result']['side'],
                                             variant=variant, **path))
    required = {}
    for r in paths:
        for ts in range(int(r.entry_ts)//60000*60000, int(r.exit_ts)//60000*60000+60000, 60000):
            month = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m')
            required.setdefault((r.contract, month), set()).add(ts)
    specs = [(kind, sym, mon, sorted(times) if kind=='markPriceKlines' else [])
             for (sym, mon), times in sorted(required.items()) for kind in ('markPriceKlines','fundingRate')]
    env, _ = risk2022.risk_namespace()
    cache = runner.ROOT / 'raw_pilot_risk_checkpoints'; cache.mkdir(exist_ok=True)
    env['WORK'] = cache
    env['FINGERPRINT'] = hashlib.sha256((sha(H/'研究冻结.json')+sha(Path(__file__))).encode()).hexdigest()
    marks, funds, statuses, sources = {}, {}, {}, []
    previous = json.loads((R90/'一秒回放批次/风险来源与结算.json').read_text(encoding='utf-8'))['sources']
    previous = {(a['kind'], a['contract'], a['month']): a for a in previous}
    for spec in specs:
        runner.guard(); a = env['task'](spec); key = spec[:3]
        statuses[key] = a['status']
        if a['status'] == 'verified':
            if key in previous: assert a['sha256'] == previous[key]['sha256']
            if a['kind'] == 'markPriceKlines':
                for row in a['rows']: marks[(a['contract'], int(row['ts']))] = row
            else: funds[(a['contract'], a['month'])] = a['rows']
        sources.append({k:v for k,v in a.items() if k!='rows'})
    for case in cases:
        settled = {}
        for variant, path in case['raw_result'].get('paths', {}).items():
            if path['status'] != 'verified': continue
            rec = SimpleNamespace(contract=case['contract'], side=case['raw_result']['side'], variant=variant, **path)
            settled[variant] = env['settle'](rec, marks, funds, statuses)
        case['risk'] = settled
    return sources


def main():
    runner.guard(start=True); freeze = frozen(); cases = []
    found = get_inputs()
    for obs in freeze['sample_ids']:
        e, cp, original = found[obs]
        try:
            tape, bars, meta, archives = load_case(e, cp)
            actual = runner.engine.decide(e, tape, bars)
            case = {'observation_id':obs, 'contract':e['contract'], 'day':e['day'],
                    'aggregate_result':original, 'raw_result':actual, 'raw_archives':archives,
                    'minute_archive':meta, 'raw_rows':len(tape)}
        except Exception as exc:
            case = {'observation_id':obs, 'contract':e['contract'], 'day':e['day'],
                    'aggregate_result':original, 'raw_result':{'status':'pilot_unknown',
                    'error':type(exc).__name__+':'+str(exc)[:200]}}
        cases.append(case)
        print('EXT97_CASE', len(cases), '/', len(freeze['sample_ids']), case['raw_result']['status'], flush=True)
    sources = settle_cases(cases)
    out = {'sample_count':len(cases), 'cases':cases, 'risk_sources':sources,
           'plan_sha256':sha(H/'研究冻结.json'), 'code_sha256':sha(Path(__file__)),
           'note':'Three previously observed samples only. Raw trade count differs from aggregate count; prints plus fixed slippage are a proxy.'}
    (H/'原始逐笔试点结果.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT97_FINISHED', len(cases), 'risk_sources', len(sources), flush=True)


if __name__ == '__main__': main()
