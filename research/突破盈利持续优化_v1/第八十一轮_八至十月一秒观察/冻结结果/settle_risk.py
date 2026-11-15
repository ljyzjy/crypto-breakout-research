"""Settle each verified first-second path using the existing risk-proxy engine."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pandas as pd
import psutil

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
sys.path.insert(0, str(H.parent / '第三十三轮_动态池逐笔执行'))
import settle_dynamic_paths as risk
import run_replay as runner

B = H / '一秒回放批次'
WORK = ROOT / 'work' / 'oneobs81_aug_oct' / 'risk'
M = 60000


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    runner.guard(start=True)
    signal_path, path_path = B / '动态池逐笔信号筛查.parquet', B / '动态池延迟市价路径.parquet'
    quality = json.loads((B / '动态池逐笔提取质量.json').read_text(encoding='utf-8'))
    assert quality['fingerprint'] == runner.fingerprint() and quality['code_sha256'] == sha(H / 'build_batch.py')
    signal, paths = pd.read_parquet(signal_path), pd.read_parquet(path_path)
    verified = paths[paths.status.eq('verified')].copy()
    if len(verified):
        data = verified.merge(signal[['observation_id', 'contract', 'side', 'source_year', 'decision_ts', 'quarter_end']],
                              on='observation_id', validate='many_to_one')
    else:
        data = verified.copy()
    required = {}
    for r in data.itertuples(index=False):
        for ts in range(int(r.entry_ts) // M * M, int(r.exit_ts) // M * M + M, M):
            month = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m')
            required.setdefault((r.contract, month), set()).add(ts)
    specs = []
    for (contract, month), times in sorted(required.items()):
        specs.extend([('markPriceKlines', contract, month, sorted(times)), ('fundingRate', contract, month, [])])
    WORK.mkdir(parents=True, exist_ok=True)
    risk.WORK = WORK
    risk.FINGERPRINT = hashlib.sha256((sha(H / '冻结时点.json') + sha(H / 'settle_risk.py') +
                                       sha(Path(risk.__file__)) + sha(path_path) + sha(signal_path)).encode()).hexdigest()
    results = []
    for spec in specs:
        runner.guard()
        rec = risk.task(spec)
        results.append(rec)
        print('EXT81_RISK_SOURCE', len(results), '/', len(specs), rec['kind'], rec['contract'], rec['month'], rec['status'], flush=True)
    marks, funds, status = {}, {}, {}
    for rec in results:
        status[(rec['kind'], rec['contract'], rec['month'])] = rec['status']
        if rec['kind'] == 'markPriceKlines':
            for x in rec['rows']:
                marks[(rec['contract'], int(x['ts']))] = x
        else:
            funds[(rec['contract'], rec['month'])] = rec['rows']
    checked = [risk.settle(r, marks, funds, status) for r in data.itertuples(index=False)]
    ledger = pd.concat([data.reset_index(drop=True), pd.DataFrame(checked)], axis=1)
    if not len(ledger):
        ledger['risk_status'] = pd.Series(dtype='object')
    ledger.to_parquet(B / '动态池单位收益与风险.parquet', index=False)
    manifest = []
    for spec, rec in zip(specs, results):
        kind, contract, month, times = spec
        digest = hashlib.sha256((risk.FINGERPRINT + '|' + kind + '|' + contract + '|' + month + '|' + ','.join(map(str, times))).encode()).hexdigest()
        cache = WORK / (digest + '.json')
        item = {k: v for k, v in rec.items() if k != 'rows'}
        item['cache_path'] = str(cache) if cache.exists() else None
        item['cache_sha256'] = sha(cache) if cache.exists() else None
        manifest.append(item)
    out = {'signal_sha256': sha(signal_path), 'paths_sha256': sha(path_path),
           'ledger_sha256': sha(B / '动态池单位收益与风险.parquet'), 'source_engine_sha256': sha(Path(risk.__file__)),
           'code_sha256': sha(Path(__file__)), 'sources': manifest, 'required_risk_groups': len(specs),
           'verified_tape_paths': len(data), 'ledger_risk_statuses': ledger.risk_status.value_counts().to_dict(),
           'note': 'Minute mark-price liquidation proxy, not exchange liquidation or account equity.'}
    (B / '风险来源与结算.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_RISK_SETTLED', json.dumps({k: v for k, v in out.items() if k != 'sources'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
