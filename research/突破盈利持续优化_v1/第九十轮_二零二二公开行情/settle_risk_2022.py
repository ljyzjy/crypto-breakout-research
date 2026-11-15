"""Settle original and extended trade paths against official 2022 mark/funding archives."""
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import pandas as pd
import replay_2022 as runner

H = Path(__file__).resolve().parent
P = H.parent
B = H / '一秒回放批次'
M = 60000
RISK_PATH = P / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py'
WORK = runner.ROOT / 'risk_checkpoints'


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read_risk_csv(body, kind):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].endswith('.csv')
        first = z.open(names[0]).readline().decode('utf-8-sig').strip()
    head = first.lower().startswith('open_time,' if kind == 'markPriceKlines' else 'calc_time,')
    cols = runner.minutes.COLS if kind == 'markPriceKlines' else ['calc_time', 'funding_interval_hours', 'last_funding_rate']
    return pd.read_csv(io.BytesIO(body), compression='zip', header=0 if head else None, names=None if head else cols)


def risk_namespace():
    original = RISK_PATH.read_text(encoding='utf-8')
    old = "d=pd.read_csv(io.BytesIO(r.content),compression='zip')"
    new = 'd=read_risk_csv(r.content,kind)'
    assert original.count(old) == 1
    adapted = original.replace(old, new)
    env = {'__name__': 'ext90_risk_engine', '__file__': str(RISK_PATH), 'read_risk_csv': read_risk_csv}
    exec(compile(adapted, str(RISK_PATH), 'exec'), env)
    env['WORK'] = WORK
    env['MIN_FREE'] = 2_200_000_000
    return env, hashlib.sha256(adapted.encode()).hexdigest()


def verify_header_compatibility():
    values = b'1640995200000,1.3,1.4,1.2,1.35,0,1640995259999,0,60,0,0,0\n'
    frames = []
    for content in (values, ','.join(runner.minutes.COLS).encode() + b'\n' + values):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('sample.csv', content)
        frames.append(read_risk_csv(memory.getvalue(), 'markPriceKlines'))
    pd.testing.assert_frame_equal(frames[0], frames[1], check_exact=True)
    assert len(frames[0]) == 1 and int(frames[0].iloc[0]['open_time']) == 1640995200000
    return {'all_checks_pass': True, 'mark_rows_checked': 1, 'code_sha256': sha(Path(__file__))}


def main():
    runner.guard(start=True)
    header_test = verify_header_compatibility()
    (H / '标记价格式合成核验.json').write_text(json.dumps(header_test, ensure_ascii=False, indent=2), encoding='utf-8')
    quality = json.loads((B / '动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    assert quality['fingerprint'] == runner.fingerprint() and quality['code_sha256'] == sha(H / 'build_batch_2022.py')
    signal_file, path_file = B / '动态池逐笔信号筛查.parquet', B / '动态池延迟市价路径.parquet'
    signals, paths = pd.read_parquet(signal_file), pd.read_parquet(path_file)
    valid = paths[paths.status.eq('verified')].copy()
    valid = valid.merge(signals[['observation_id', 'contract', 'side', 'source_year', 'decision_ts', 'quarter_end']],
                        on='observation_id', validate='many_to_one')
    required = {}
    for r in valid.itertuples(index=False):
        for ts in range(int(r.entry_ts) // M * M, int(r.exit_ts) // M * M + M, M):
            mon = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m')
            required.setdefault((r.contract, mon), set()).add(ts)
    specs = []
    for (sym, mon), times in sorted(required.items()):
        specs += [('markPriceKlines', sym, mon, sorted(times)), ('fundingRate', sym, mon, [])]
    WORK.mkdir(parents=True, exist_ok=True)
    risk, adapted_sha = risk_namespace()
    fp = hashlib.sha256((sha(H / '冻结时点.json') + sha(Path(__file__)) + sha(RISK_PATH) + sha(path_file) + sha(signal_file)).encode()).hexdigest()
    risk['FINGERPRINT'] = fp
    results = []
    for spec in specs:
        runner.guard()
        result = risk['task'](spec)
        results.append(result)
        print('EXT90_RISK_SOURCE', len(results), '/', len(specs), result['kind'], result['contract'], result['month'], result['status'], flush=True)
    marks, funds, statuses, manifest = {}, {}, {}, []
    for spec, result in zip(specs, results):
        kind, sym, mon, times = spec
        statuses[(kind, sym, mon)] = result['status']
        if result['status'] == 'verified':
            if kind == 'markPriceKlines':
                for x in result['rows']: marks[(sym, int(x['ts']))] = x
            else: funds[(sym, mon)] = result['rows']
        key = hashlib.sha256((fp + '|' + kind + '|' + sym + '|' + mon + '|' + ','.join(map(str, times))).encode()).hexdigest()
        cache = WORK / (key + '.json')
        meta = {k: v for k, v in result.items() if k != 'rows'}
        meta.update(cache_path=str(cache) if cache.exists() else None, cache_sha256=sha(cache) if cache.exists() else None)
        manifest.append(meta)
    checked = [risk['settle'](r, marks, funds, statuses) for r in valid.itertuples(index=False)]
    ledger = pd.concat([valid.reset_index(drop=True), pd.DataFrame(checked)], axis=1)
    if not len(ledger): ledger['risk_status'] = pd.Series(dtype='object')
    ledger_path = B / '动态池单位收益与风险.parquet'
    ledger.to_parquet(ledger_path, index=False)
    out = {'signal_sha256': sha(signal_file), 'paths_sha256': sha(path_file), 'ledger_sha256': sha(ledger_path),
           'source_engine_sha256': sha(RISK_PATH), 'adapted_engine_sha256': adapted_sha,
           'code_sha256': sha(Path(__file__)), 'sources': manifest, 'required_risk_groups': len(specs),
           'verified_tape_paths': len(valid), 'ledger_risk_statuses': ledger.risk_status.value_counts().to_dict(),
           'note': 'Header adaptation only; minute mark-price proxy is not exchange liquidation or account equity.'}
    (B / '风险来源与结算.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_RISK_SETTLED', json.dumps({k: v for k, v in out.items() if k != 'sources'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
