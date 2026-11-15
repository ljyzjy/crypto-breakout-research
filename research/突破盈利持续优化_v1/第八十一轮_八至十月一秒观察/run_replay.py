"""Resumable streaming first-second replay for all frozen Aug-Oct candidates."""
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
OLD = P / '第六十三轮_2026八至十月延伸'
R62 = P / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(P / '第三十三轮_动态池逐笔执行'))
import extract_dynamic_tapes as minutes
sys.path.insert(0, str(P / '第四十八轮_固定一倍风险止盈'))
import public_range
sys.path.insert(0, str(R62))
import one_second_observation as engine

M = 60000
WORK = ROOT / 'work' / 'oneobs81_aug_oct' / 'tape'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def guard(start=False):
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError('disk_headroom')
    minimum = 850 if start else 300
    if psutil.virtual_memory().available < minimum * 1024**2:
        raise RuntimeError('memory_headroom')


def verify_inputs():
    f = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == f['plan_sha256']
    assert sha(OLD / '延伸候选准备质量.json') == f['candidate_quality_sha256']
    assert sha(OLD / '候选数据/固定十一币双币过滤潜在触价.parquet') == f['candidate_sha256']
    assert sha(OLD / '行情代码冻结哈希.json') == f['source_sha256']
    assert sha(R62 / '冻结研究方案.md') == f['one_second_plan_sha256']
    assert sha(R62 / 'one_second_observation.py') == f['one_second_engine_sha256']
    assert sha(R62 / '一秒观察合成时序核验.json') == f['one_second_tests_sha256']
    proof = json.loads((OLD / '延伸候选独立核验总表.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['inputs_unchanged']
    assert proof['rank_audit_sha256'] == sha(OLD / '延伸日小时排名独立核验.json')
    assert proof['candidate_audit_sha256'] == sha(OLD / '延伸候选特征独立核验.json')
    sources = json.loads((OLD / '行情代码冻结哈希.json').read_text(encoding='utf-8'))['source']
    for info in sources.values():
        assert sha(Path(info['path'])) == info['sha256']
    return f, sources


def fingerprint():
    files = [H / '冻结时点.json', Path(__file__), OLD / '延伸候选独立核验总表.json',
             R62 / 'one_second_observation.py', P / '第三十三轮_动态池逐笔执行/leveraged_paths.py',
             P / '第三十三轮_动态池逐笔执行/extract_dynamic_tapes.py',
             P / '第四十八轮_固定一倍风险止盈/public_range.py',
             P / '第四十七轮_一次重新突破确认/public_tape_stream.py']
    return hashlib.sha256(''.join(sha(x) for x in files).encode()).hexdigest()


def checkpoint_key(fp, sym, day, needs, events):
    text = '|'.join([fp, sym, day, str(needs), *sorted(e['observation_id'] for e in events)])
    return hashlib.sha256(text.encode()).hexdigest()


def execute(fp, sym, day, needs, events, norm):
    target = WORK / (checkpoint_key(fp, sym, day, needs, events) + '.json')
    if target.exists():
        z = json.loads(target.read_text(encoding='utf-8'))
        assert z['fingerprint'] == fp and z['status'] == 'verified'
        return z
    err = ''
    for attempt in range(3):
        try:
            guard()
            body, bar_meta = minutes.archive('klines', sym, day)
            bars = minutes.minute_bars(body, day)
            del body
            good, bad = [], {}
            for e in events:
                times = range(int(e['quarter_start']), int(e['trigger_minute']) + M, M)
                cols = ['open', 'high', 'low', 'close']
                lhs, rhs = norm.reindex(times)[cols].to_numpy(float), bars.reindex(times)[cols].to_numpy(float)
                if not np.isfinite(lhs).all() or not np.isfinite(rhs).all() or not np.allclose(lhs, rhs, rtol=1e-9, atol=1e-12):
                    bad[e['observation_id']] = 'daily_monthly_ohlc_mismatch'
                elif e['market_prior_status'] != 'allowed':
                    bad[e['observation_id']] = 'market_source_unknown'
                else:
                    good.append(e)
            dates = [day]
            if needs:
                dates.append((pd.Timestamp(day, tz='UTC') + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
            archives, blocks = [bar_meta], {e['observation_id']: [] for e in good}
            for date in dates:
                if not good:
                    break
                windows = {e['observation_id']: (int(e['trigger_minute']), int(e['quarter_end']) + M) for e in good}
                found, info = public_range.fetch(sym, date, windows, guard)
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
                    rows.append({'observation_id': obs, **engine.decide(e, tape, bars)})
            out = {'status': 'verified', 'fingerprint': fp, 'contract': sym, 'day': day, 'needs_next': needs,
                   'archives': archives, 'rows': rows}
            guard()
            temp = target.with_suffix('.partial')
            temp.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            temp.replace(target)
            return out
        except Exception as exc:
            err = type(exc).__name__ + ':' + str(exc)[:180]
            if any(x in err for x in ('headroom', 'stream_cap', 'window_exceeds', '404')):
                break
            if attempt < 2:
                print('EXT81_RETRY', sym, day, attempt + 1, type(exc).__name__, flush=True)
                time.sleep(attempt + 1)
    return {'status': 'error', 'error': err, 'contract': sym, 'day': day}


def main():
    guard(start=True)
    f, sources = verify_inputs()
    data = pd.read_parquet(OLD / '候选数据/固定十一币双币过滤潜在触价.parquet')
    assert len(data) == 57 and data.observation_id.is_unique
    fp = fingerprint()
    WORK.mkdir(parents=True, exist_ok=True)
    groups = [(s, day, bool(needs), g.to_dict('records')) for (s, day, needs), g in data.groupby(['contract', 'day', 'needs_next'], sort=True)]
    current, norm, completed, errors = None, None, 0, []
    print('EXT81_START', len(groups), 'groups', len(data), 'candidates', flush=True)
    for sym, day, needs, events in groups:
        try:
            guard()
            if sym != current:
                norm = pd.read_parquet(Path(sources[sym]['path']), columns=['ts', 'open', 'high', 'low', 'close']).set_index('ts')
                assert norm.index.is_unique
                current = sym
            z = execute(fp, sym, day, needs, events, norm)
        except Exception as exc:
            z = {'status': 'error', 'contract': sym, 'day': day, 'error': type(exc).__name__ + ':' + str(exc)[:180]}
        if z['status'] == 'verified':
            completed += 1
        else:
            errors.append({k: z[k] for k in ('contract', 'day', 'error')})
        print('EXT81_GROUP', completed, '/', len(groups), 'errors', len(errors), sym, day, z['status'], flush=True)
        if z['status'] != 'verified' and 'headroom' in z['error']:
            break
    progress = {'total_candidates': len(data), 'total_groups': len(groups), 'completed_groups': completed,
                'errors': errors, 'fingerprint': fp, 'frozen_sha256': sha(H / '冻结时点.json'),
                'note': 'Checkpoints are not settled, independently audited or account results.'}
    (H / '一秒逐笔回放进度.json').write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_STOP', json.dumps(progress, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
