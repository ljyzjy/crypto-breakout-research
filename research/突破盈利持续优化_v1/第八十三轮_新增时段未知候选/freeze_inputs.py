import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
R81 = H.parent / '第八十一轮_八至十月一秒观察'
sys.path.insert(0, str(R81))
import run_replay as runner


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    out_path = H / '冻结时点.json'
    assert not out_path.exists()
    sig_path = R81 / '一秒回放批次/动态池逐笔信号筛查.parquet'
    sig = pd.read_parquet(sig_path)
    unknown = sig.loc[sig.status.eq('minute_trade_ohlc_mismatch')]
    assert len(unknown) == 3
    fp = runner.fingerprint()
    candidates = pd.read_parquet(runner.OLD / '候选数据/固定十一币双币过滤潜在触价.parquet')
    records = []
    for (sym, day, needs), group in candidates.groupby(['contract', 'day', 'needs_next'], sort=True):
        chosen = group[group.observation_id.isin(unknown.observation_id)]
        if chosen.empty:
            continue
        events = group.to_dict('records')
        cp = runner.WORK / (runner.checkpoint_key(fp, sym, day, bool(needs), events) + '.json')
        z = json.loads(cp.read_text(encoding='utf-8'))
        for e in chosen.to_dict('records'):
            row = next(x for x in z['rows'] if x['observation_id'] == e['observation_id'])
            assert row['status'] == 'minute_trade_ohlc_mismatch'
            records.append({'observation_id': e['observation_id'], 'contract': sym, 'day': day,
                            'checkpoint': str(cp), 'checkpoint_sha256': sha(cp), 'archives': z['archives']})
    assert len(records) == 3 and {r['observation_id'] for r in records} == set(unknown.observation_id)
    result = {'plan_sha256': sha(H / '冻结研究方案.md'), 'r81_frozen_sha256': sha(R81 / '冻结结果/冻结哈希.json'),
              'signals_sha256': sha(sig_path), 'candidate_sha256': sha(runner.OLD / '候选数据/固定十一币双币过滤潜在触价.parquet'),
              'r81_runner_sha256': sha(R81 / 'run_replay.py'), 'one_second_engine_sha256': sha(runner.R62 / 'one_second_observation.py'),
              'reference_check_sha256': sha(H.parent / '第八十轮_未知候选一秒复核/one_second_check.py'),
              'candidates': sorted(records, key=lambda x: x['observation_id']), 'frozen_utc': datetime.now(timezone.utc).isoformat(),
              'note': 'All three unknown candidates, fixed before raw-data results.'}
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT83_FROZEN', sha(out_path), 'candidates', len(records), flush=True)


if __name__ == '__main__':
    main()
