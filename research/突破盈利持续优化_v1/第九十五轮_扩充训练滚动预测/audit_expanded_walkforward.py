"""Independently rebuild features, Newton fits, chronology and forward scores."""
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R77 = P / '第七十七轮_滚动事前模型'
R90 = P / '第九十轮_二零二二公开行情'
R93 = P / '第九十三轮_原始逐笔抽样交叉核验'
R81 = P / '第八十一轮_八至十月一秒观察'
R82 = P / '第八十二轮_八至十月持仓量过滤'
sys.path.insert(0, str(R77)); import audit_walkforward as independent
sys.path.insert(0, str(R90)); import replay_2022 as guard
CASES = [('2023', ('2022',)), ('2024', ('2022', '2023')),
         ('2026', ('2022', '2023', '2024')), ('2026_aug_oct', ('2022', '2023', '2024'))]
FEATURES = independent.FEATURES


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def close(a, b, tol=1e-9):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)


def custom_load(period):
    if period == '2022':
        folder = R90 / '一秒回放批次'; oi_path = R90 / '持仓量逐点来源核验.json'
        bad = {x['observation_id'] for x in json.loads((R93 / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))['samples'] if x['status'] != 'agree'}
        ledger = pd.read_parquet(folder / '动态池单位收益与风险.parquet'); ledger = ledger[ledger.holding_rule.eq('original')]
    else:
        folder = R81 / '冻结结果/batch'; oi_path = R82 / '持仓量逐点来源核验.json'; bad = set()
        ledger = pd.read_parquet(folder / '动态池单位收益与风险.parquet')
    signals = pd.read_parquet(folder / '动态池逐笔信号筛查.parquet').set_index('observation_id').to_dict('index')
    oi = json.loads(oi_path.read_text(encoding='utf-8'))
    events = {x['observation_id']: x for x in oi['events']}
    points = {(x['symbol'], int(x['ts'])): x for x in oi['points']}
    data = []
    for row in ledger.to_dict('records'):
        obs = row['observation_id']
        if obs in bad or row['status'] != 'verified' or row['risk_status'] != 'verified' or bool(row['liq_proxy']): continue
        s = signals[obs]; e = events.get(obs); o = {'oi_status': 'unknown'}
        if e is not None:
            t = int(e['oi_t0']); assert t == (int(s['decision_ts']) - 900000) // 300000 * 300000 and int(e['oi_previous']) == t - 3600000
            changes = {}
            for sym, tag in [('BTCUSDT', 'btc'), ('ETHUSDT', 'eth')]:
                x, y = points.get((sym, t)), points.get((sym, t - 3600000))
                if not x or not y or x['status'] != 'verified' or y['status'] != 'verified': break
                a, b = Decimal(x['official_values'][0]), Decimal(y['official_values'][0]); assert a > 0 and b > 0
                changes[tag + '_change'] = float(a / b - 1)
            if len(changes) == 2: o = {'oi_status': 'verified', **changes}
        assert int(row['entry_ts']) >= int(s['entry_exec_ts']) + 1000 and int(s['entry_exec_ts']) >= int(s['decision_ts']) + 1000
        data.append({'year': period, 'observation_id': obs, 'variant': row['variant'], 'features': independent.feature(s, o),
                     'net': float(row['net_per_unit_notional']), 'decision_ts': int(s['decision_ts']),
                     'entry_ts': int(row['entry_ts']), 'exit_ts': int(row['exit_ts'])})
    return data


def quality(scored, prior):
    if not scored: return {'brier': None, 'constant_brier': None, 'auc': None}
    pairs = [(p, r['net'] > 0) for r, p in scored]
    brier = math.fsum((p - int(y)) ** 2 for p, y in pairs) / len(pairs)
    constant = math.fsum((prior - int(y)) ** 2 for p, y in pairs) / len(pairs)
    pos, neg = [p for p, y in pairs if y], [p for p, y in pairs if not y]
    auc = sum(int(a > b) + .5 * int(a == b) for a in pos for b in neg) / (len(pos) * len(neg)) if pos and neg else None
    return {'brier': brier, 'constant_brier': constant, 'auc': auc}


def main():
    guard.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for k, p in frozen['source_paths'].items(): assert sha(Path(p)) == frozen['source_sha256'][k]
    path = H / '扩充训练滚动结果.json'; result = json.loads(path.read_text(encoding='utf-8'))
    assert result['frozen_sha256'] == sha(H / '冻结时点.json') and result['code_sha256'] == sha(H / 'run_expanded_walkforward.py')
    assert result['model_parameters_sha256'] == sha(H / '滚动模型参数.json')
    assert result['train_detail_sha256'] == sha(H / '滚动训练明细.csv') and result['score_detail_sha256'] == sha(H / '滚动评分明细.csv')
    models = json.loads((H / '滚动模型参数.json').read_text(encoding='utf-8'))['models']
    with (H / '滚动训练明细.csv').open(encoding='utf-8', newline='') as f: train_details = list(csv.DictReader(f))
    with (H / '滚动评分明细.csv').open(encoding='utf-8', newline='') as f: score_details = list(csv.DictReader(f))
    datasets = {'2022': custom_load('2022'), '2026_aug_oct': custom_load('2026_aug_oct')}
    f77 = json.loads((R77 / '冻结时点.json').read_text(encoding='utf-8'))
    baselines = {}
    for year in ('2023', '2024', '2026'): datasets[year], baselines[year] = independent.load(year, f77)
    late = json.loads((R81 / '八至十月一秒观察结果.json').read_text(encoding='utf-8'))['rows']
    checked = 0
    for period, years in CASES:
      for lev in (10, 20):
        variant = f'one_observation_2r_{lev}x'
        testing = [r for r in datasets[period] if r['variant'] == variant]
        first = min(r['decision_ts'] for r in testing)
        train_all = [r for year in years for r in datasets[year] if r['variant'] == variant]
        train = [r for r in train_all if r['features'] is not None and r['exit_ts'] < first]
        meta = next(x for x in models if x['test_period'] == period and x['leverage'] == lev)
        assert meta['training_rows'] == len(train) and meta['training_wins'] == sum(r['net'] > 0 for r in train)
        assert meta['train_exit_not_earlier'] == sum(r['exit_ts'] >= first for r in train_all) and meta['test_first_decision_ts'] == first
        x = np.asarray([r['features'] for r in train], float); y = np.asarray([r['net'] > 0 for r in train], float)
        mean, std = x.mean(axis=0), x.std(axis=0); std = np.where(std > 1e-12, std, 1.)
        design = np.clip((x - mean) / std, -5., 5.)
        beta = independent.newton(design, y)
        assert np.allclose(meta['mean'], mean, rtol=1e-10, atol=1e-10) and np.allclose(meta['std'], std, rtol=1e-10, atol=1e-10)
        assert np.allclose(meta['beta'], beta, rtol=1e-5, atol=1e-5)
        gains, loss = [r['net'] for r in train if r['net'] > 0], [r['net'] for r in train if r['net'] <= 0]
        win, nonwin = math.fsum(gains) / len(gains), math.fsum(loss) / len(loss)
        assert close(meta['mean_win_fraction'], win, 1e-11) and close(meta['mean_nonwin_fraction'], nonwin, 1e-11)
        assert close(meta['breakeven_probability'], -nonwin / (win - nonwin), 1e-11)
        trows = [r for r in train_details if r['test_period'] == period and r['leverage'] == str(lev)]
        by_train = {(r['source_year'], r['observation_id']): r for r in trows}; assert len(by_train) == len(train)
        for r in train:
            z = by_train[(r['year'], r['observation_id'])]
            assert int(z['decision_ts']) == r['decision_ts'] and int(z['exit_ts']) == r['exit_ts'] and close(z['net'], r['net'], 1e-11)
            assert all(close(z[k], value, 1e-10) for k, value in zip(FEATURES, r['features']))
        srows = [r for r in score_details if r['test_period'] == period and r['leverage'] == str(lev)]
        by_score = {r['observation_id']: r for r in srows}; assert len(by_score) == len(testing)
        selected, scored, unknown, rejected = [], [], 0, 0
        for r in testing:
            z = by_score[r['observation_id']]
            assert int(z['decision_ts']) == r['decision_ts'] and int(z['entry_ts']) == r['entry_ts'] and int(z['exit_ts']) == r['exit_ts'] and close(z['net'], r['net'], 1e-11)
            if r['features'] is None:
                assert z['status'] == 'unknown_feature'; unknown += 1; continue
            assert all(close(z[k], value, 1e-10) for k, value in zip(FEATURES, r['features']))
            transformed = np.clip((np.asarray(r['features']) - mean) / std, -5., 5.)
            p = float(independent.sigmoid(beta[0] + transformed @ beta[1:])); ev = p * win + (1 - p) * nonwin
            assert close(z['probability'], p, 1e-5) and close(z['expected_net_fraction'], ev, 1e-6)
            assert z['selected'] == str(ev > 0)
            scored.append((r, p))
            if ev > 0: selected.append(r)
            else: rejected += 1
            checked += 1
        row = next(x for x in result['rows'] if x['test_period'] == period and x['leverage'] == lev)
        assert row['train_rows'] == len(train) and row['scored'] == len(scored) and row['feature_unknown'] == unknown and row['model_rejected'] == rejected
        if period == '2026_aug_oct':
            ref = next(x for x in late if x['leverage'] == lev and x['exit_slippage_pct'] == .05)
            base_unknown, no_order, candidates = ref['unknown_candidates'], ref['known_no_order'], ref['candidate_events']
        else:
            ref = next(x for x in baselines[period] if x['leverage'] == lev)
            base_unknown, no_order, candidates = ref['one_second_observation']['unknown'], ref['known_no_order'], ref['candidate_events']
        assert len(selected) + base_unknown + unknown + no_order + rejected == candidates == row['candidate_events']
        assert row['known_no_order'] == no_order + rejected
        for field, expected in independent.calc_stats(testing, base_unknown).items(): assert close(row['baseline'][field], expected, 1e-9)
        for field, expected in independent.calc_stats(selected, base_unknown + unknown).items(): assert close(row['model'][field], expected, 1e-9)
        for field, expected in quality(scored, len(gains) / len(train)).items(): assert close(row['prediction_quality'][field], expected, 1e-5)
    assert checked == result['future_test_rows_perturbed']
    out = {'all_checks_pass': True, 'model_groups_checked': len(result['rows']), 'scored_paths_checked': checked,
           'result_sha256': sha(path), 'code_sha256': sha(Path(__file__)), 'independent_optimizer_sha256': sha(R77 / 'audit_walkforward.py'),
           'note': 'Chronological retrospective audit; prior exposure, aggregated-trade ambiguity and actual OI release times remain.'}
    (H / '扩充滚动模型独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT95_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
