"""Resumable 2022 official trade-tape replay under the frozen entry and exit rules."""
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import zipfile

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
sys.path.insert(0, str(P / '第三十三轮_动态池逐笔执行'))
import extract_dynamic_tapes as minutes
sys.path.insert(0, str(P / '第四十八轮_固定一倍风险止盈'))
import public_range
sys.path.insert(0, str(P / '第六十二轮_一秒观察更早突破'))
import one_second_observation as engine
sys.path.insert(0, str(P / '第八十八轮_延长一根柱持有'))
from extend_exit import extend_path
import acquire_klines as guarded

M, EXTRA = 60000, 900000
FROZEN = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
ROOT = Path(FROZEN['data_root'])
WORK = ROOT / 'one_second_tape_checkpoints'
TRADE_COLUMNS = b'agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def guard(start=False):
    guarded.guard(ROOT, start=start)


def minute_bars(body, day):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].endswith('.csv')
        first = z.open(names[0]).readline().decode('utf-8-sig').strip()
    header = first.lower().startswith('open_time,')
    d = pd.read_csv(io.BytesIO(body), compression='zip', header=0 if header else None,
                    names=None if header else minutes.COLS)
    d = d[['open_time', 'open', 'high', 'low', 'close']].apply(pd.to_numeric, errors='raise')
    lo = int(pd.Timestamp(day, tz='UTC').timestamp() * 1000)
    assert not d.open_time.duplicated().any() and (d.open_time % M == 0).all()
    assert d.open_time.between(lo, lo + 86400000 - 1).all()
    return d.set_index('open_time')


def install_header_compatible_reader():
    path = P / '第四十七轮_一次重新突破确认/public_tape_stream.py'
    source = path.read_text(encoding='utf-8')
    old = "header=line.rstrip(b'\\r');names=header.decode('utf-8-sig').split(',')\n            if not set(COLS).issubset(names):raise ValueError('unexpected_csv_header')"
    new = """header=line.rstrip(b'\\r');names=header.decode('utf-8-sig').split(',')
            if not set(COLS).issubset(names):
                if len(names)!=7:raise ValueError('unexpected_headerless_columns')
                int(names[0]);float(names[1]);float(names[2]);int(names[3]);int(names[4]);int(names[5])
                if names[6].lower() not in ('true','false'):raise ValueError('unexpected_headerless_maker')
                part=header+b'\\n'+part
                header=b'agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker'"""
    assert source.count(old) == 1
    changed = source.replace(old, new)
    namespace = {'__name__': 'ext90_header_compatible_stream', '__file__': str(path)}
    exec(compile(changed, str(path), 'exec'), namespace)
    parse = namespace['parse_stream']
    rows = b'42,3.1,5,1,2,1642723200023,true\n43,3.2,6,3,4,1642723200100,false\n'
    frames = []
    for content in (rows, TRADE_COLUMNS + b'\n' + rows):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('sample.csv', content)
        blob = b.getvalue()
        chunks = (blob[i:i + 17] for i in range(0, len(blob), 17))
        out, meta = parse(chunks, hashlib.sha256(blob).hexdigest(), {'s': (1642723200000, 1642723201000)}, len(blob))
        assert meta['windows']['s'] == 2
        frames.append(pd.concat(out['s'], ignore_index=True))
    pd.testing.assert_frame_equal(frames[0], frames[1], check_exact=True)
    assert list(frames[0].agg_trade_id) == [42, 43]
    public_range.original.parse_stream = parse
    return {'all_checks_pass': True, 'legacy_header_and_headerless_rows_equal': 2,
            'patched_reader_sha256': hashlib.sha256(changed.encode()).hexdigest(),
            'note': 'Only CSV header handling changed; full ZIP SHA and original streamed parser retained.'}


def verify_inputs():
    assert sha(H / '冻结研究方案.md') == FROZEN['plan_sha256']
    for k, p in FROZEN['source_paths'].items():
        assert sha(Path(p)) == FROZEN['source_sha256'][k], k
    quality = json.loads((H / '二零二二候选准备质量.json').read_text(encoding='utf-8'))
    audit = json.loads((H / '二零二二候选独立核验总表.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['inputs_unchanged']
    assert audit['candidate_quality_sha256'] == sha(H / '二零二二候选准备质量.json')
    assert audit['rank_audit_sha256'] == sha(H / '二零二二日小时排名独立核验.json')
    assert audit['event_audit_sha256'] == sha(H / '二零二二候选特征独立核验.json')
    assert audit['wrapper_sha256'] == sha(H / 'audit_candidates_2022.py')
    for name, digest in quality['outputs_sha256'].items():
        assert sha(H / '候选数据' / name) == digest
    sources = {x['symbol']: x for x in audit['sources']}
    for x in sources.values(): assert sha(Path(x['path'])) == x['sha256']
    return sources


def fingerprint():
    files = [H / '冻结时点.json', H / '二零二二候选独立核验总表.json', Path(__file__),
             P / '第三十三轮_动态池逐笔执行/extract_dynamic_tapes.py',
             P / '第三十三轮_动态池逐笔执行/leveraged_paths.py',
             P / '第六十二轮_一秒观察更早突破/one_second_observation.py',
             P / '第八十八轮_延长一根柱持有/extend_exit.py',
             P / '第四十八轮_固定一倍风险止盈/public_range.py',
             P / '第四十七轮_一次重新突破确认/public_tape_stream.py']
    return hashlib.sha256(''.join(sha(x) for x in files).encode()).hexdigest()


def key(fp, symbol, day, events):
    v = '|'.join([fp, symbol, day, *sorted(e['observation_id'] for e in events)])
    return hashlib.sha256(v.encode()).hexdigest()


def execute(fp, symbol, day, events, norm):
    target = WORK / (key(fp, symbol, day, events) + '.json')
    if target.exists():
        saved = json.loads(target.read_text(encoding='utf-8'))
        assert saved['status'] == 'verified' and saved['fingerprint'] == fp
        return saved
    error = ''
    for attempt in range(3):
        try:
            guard()
            body, bar_meta = minutes.archive('klines', symbol, day)
            bars = minute_bars(body, day)
            del body
            good, bad = [], {}
            for e in events:
                times = range(int(e['quarter_start']), int(e['trigger_minute']) + M, M)
                cols = ['open', 'high', 'low', 'close']
                a, b = norm.reindex(times)[cols].to_numpy(float), bars.reindex(times)[cols].to_numpy(float)
                if not np.isfinite(a).all() or not np.isfinite(b).all() or not np.allclose(a, b, rtol=1e-9, atol=1e-12):
                    bad[e['observation_id']] = 'daily_monthly_ohlc_mismatch'
                elif e['market_prior_status'] != 'allowed':
                    bad[e['observation_id']] = 'market_source_unknown'
                else:
                    good.append(e)
            end = max(int(e['quarter_end']) + EXTRA + M for e in events)
            dates = pd.date_range(pd.Timestamp(day, tz='UTC'), pd.Timestamp(end - 1, unit='ms', tz='UTC').normalize(), freq='D').strftime('%Y-%m-%d').tolist()
            archives, blocks = [bar_meta], {e['observation_id']: [] for e in good}
            for date in dates:
                if not good: break
                windows = {e['observation_id']: (int(e['trigger_minute']), int(e['quarter_end']) + EXTRA + M) for e in good}
                found, info = public_range.fetch(symbol, date, windows, guard)
                archives.append(info)
                for e in good:
                    blocks[e['observation_id']].extend(found[e['observation_id']])
            rows = []
            for e in events:
                obs = e['observation_id']
                if obs in bad:
                    rows.append({'observation_id': obs, 'status': bad[obs]})
                elif not blocks[obs]:
                    rows.append({'observation_id': obs, 'status': 'missing_event_tape'})
                else:
                    tape = pd.concat(blocks[obs], ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
                    decision = engine.decide(e, tape, bars)
                    extended = {}
                    for variant, original in decision.get('paths', {}).items():
                        if original['status'] != 'verified' or original.get('reason') != 'quarter_time':
                            extended[variant] = dict(original)
                        else:
                            prices = list(zip(tape.transact_time.astype('int64'), tape.price.astype(float)))
                            extended[variant] = extend_path({**original, 'side': decision['side'], 'quarter_end': e['quarter_end']}, prices)
                            del prices
                    rows.append({'observation_id': obs, **decision, 'extended_paths': extended})
                    del tape
            out = {'status': 'verified', 'fingerprint': fp, 'contract': symbol, 'day': day,
                   'archives': archives, 'rows': rows}
            guard()
            tmp = target.with_suffix('.partial')
            tmp.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            tmp.replace(target)
            return out
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)[:180]
            if any(x in error for x in ('headroom', 'stream_cap', 'window_exceeds', '404')):
                break
            if attempt < 2:
                print('EXT90_RETRY', symbol, day, attempt + 1, error, flush=True)
                time.sleep(attempt + 1)
    return {'status': 'error', 'error': error, 'contract': symbol, 'day': day}


def main():
    guard(start=True)
    sources = verify_inputs()
    format_check = install_header_compatible_reader()
    (H / '历史无表头格式合成核验.json').write_text(json.dumps(format_check, ensure_ascii=False, indent=2), encoding='utf-8')
    candidates = pd.read_parquet(H / '候选数据/固定十一币双币过滤潜在触价.parquet')
    assert len(candidates) == 310 and candidates.observation_id.is_unique
    groups = [(sym, day, g.to_dict('records')) for (sym, day), g in candidates.groupby(['contract', 'day'], sort=True)]
    fp = fingerprint()
    WORK.mkdir(parents=True, exist_ok=True)
    current, norm, done, errors = None, None, 0, []
    print('EXT90_START', len(groups), 'groups', len(candidates), 'candidates', flush=True)
    for symbol, day, events in groups:
        try:
            guard()
            if symbol != current:
                norm = pd.read_parquet(sources[symbol]['path'], columns=['ts', 'open', 'high', 'low', 'close']).set_index('ts')
                assert norm.index.is_unique
                current = symbol
            result = execute(fp, symbol, day, events, norm)
        except Exception as exc:
            result = {'status': 'error', 'contract': symbol, 'day': day, 'error': type(exc).__name__ + ':' + str(exc)[:180]}
        if result['status'] == 'verified': done += 1
        else: errors.append({k: result[k] for k in ('contract', 'day', 'error')})
        print('EXT90_GROUP', done, '/', len(groups), 'errors', len(errors), symbol, day, result['status'], flush=True)
        if result['status'] != 'verified' and 'headroom' in result['error']: break
    progress = {'total_candidates': len(candidates), 'total_groups': len(groups), 'completed_groups': done,
                'errors': errors, 'fingerprint': fp, 'frozen_sha256': sha(H / '冻结时点.json'),
                'note': 'Checkpoints only; neither independent path audit nor risk settlement is complete.'}
    (H / '一秒逐笔回放进度.json').write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_STOP', json.dumps(progress, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
