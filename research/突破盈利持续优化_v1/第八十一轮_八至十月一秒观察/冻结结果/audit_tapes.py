"""Independently replay selected complete first-second paths from official tapes."""
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R62 = P / '第六十二轮_一秒观察更早突破'
OLD = P / '第六十三轮_2026八至十月延伸'
sys.path.insert(0, str(R62))
import audit_tape_samples as scalar
sys.path.insert(0, str(P / '第四十七轮_一次重新突破确认'))
import public_tape_stream as stream
sys.path.insert(0, str(P / '第三十三轮_动态池逐笔执行'))
import extract_dynamic_tapes as minutes
import run_replay as runner


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    runner.guard(start=True)
    test = json.loads((R62 / '独立重放合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['audit_code_sha256'] == sha(R62 / 'audit_tape_samples.py')
    assert test['decision_code_sha256'] == sha(R62 / 'one_second_observation.py')
    candidates = pd.read_parquet(OLD / '候选数据/固定十一币双币过滤潜在触价.parquet')
    fp, available = runner.fingerprint(), []
    known = {'first_direction_ineligible', 'no_order_time', 'flow_filter_not_met', 'known_risk_rejected', 'qualified'}
    for (sym, day, needs), group in candidates.groupby(['contract', 'day', 'needs_next'], sort=True):
        events = group.to_dict('records')
        path = runner.WORK / (runner.checkpoint_key(fp, sym, day, bool(needs), events) + '.json')
        if not path.exists():
            continue
        cp = json.loads(path.read_text(encoding='utf-8'))
        assert cp['status'] == 'verified' and cp['fingerprint'] == fp
        indexed = {x['observation_id']: x for x in cp['rows']}
        for event in events:
            row = indexed[event['observation_id']]
            if row['status'] in known:
                available.append((event, cp, row))
    available.sort(key=lambda x: (sum(a.get('bytes', 0) for a in x[1]['archives'] if a['kind'] == 'aggTrades'), x[0]['observation_id']))
    chosen = []
    for status in ('qualified', 'flow_filter_not_met', 'known_risk_rejected'):
        x = next((v for v in available if v[2]['status'] == status and v not in chosen), None)
        if x:
            chosen.append(x)
    for cohort in ('opening', 'touch'):
        x = next((v for v in available if v[0]['cohort'] == cohort and v not in chosen), None)
        if x and len(chosen) < 5:
            chosen.append(x)
    assert len(chosen) >= 3
    samples = []
    for event, cp, row in chosen:
        runner.guard()
        obs = event['observation_id']
        body, bar_meta = minutes.archive('klines', event['contract'], event['day'])
        bars = minutes.minute_bars(body, event['day'])
        del body
        original_bar = next(x for x in cp['archives'] if x['kind'] == 'klines')
        assert original_bar['sha256'] == bar_meta['sha256']
        blocks, archives = [], []
        for old in (x for x in cp['archives'] if x['kind'] == 'aggTrades'):
            found, meta = stream.fetch(event['contract'], old['day'], {obs: (int(event['trigger_minute']), int(event['quarter_end']) + 60000)}, runner.guard)
            assert meta['sha256'] == old['sha256'] and meta['bytes'] == old['bytes']
            blocks.extend(found[obs]); archives.append(meta)
        assert blocks
        tape = pd.concat(blocks, ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
        n = scalar.replay(event, tape, bars, row)
        samples.append({'observation_id': obs, 'status': row['status'], 'paths_checked': n,
                        'minute_sha256': bar_meta['sha256'], 'tape_archives': archives})
        print('EXT81_SAMPLE', len(samples), '/', len(chosen), flush=True)
    out = {'all_checks_pass': True, 'samples': samples, 'paths_checked': sum(x['paths_checked'] for x in samples),
           'batch_fingerprint': fp, 'scalar_audit_sha256': sha(R62 / 'audit_tape_samples.py'),
           'scalar_test_sha256': sha(R62 / '独立重放合成核验.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Sample audits from the same public exchange; not real orders.'}
    (H / '一秒逐笔独立样本核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_SAMPLE_PASS', len(samples), out['paths_checked'], flush=True)


if __name__ == '__main__':
    main()
