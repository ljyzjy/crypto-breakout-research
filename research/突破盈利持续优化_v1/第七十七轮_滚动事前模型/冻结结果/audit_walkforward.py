"""Independent feature, convex-optimum, chronology and scoring verification."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
FEATURES = ['one_imbalance', 'log_one_count', 'directional_first_second_extension_atr',
            'directional_stop_distance', 'quarter_elapsed_fraction', 'side', 'btc_oi_change', 'eth_oi_change']


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -700, 700)))


def feature(s, o):
    try:
        if o.get('oi_status') != 'verified':
            return None
        side, count = int(s['side']), int(s['one_count'])
        decision, start, end = int(s['decision_ts']), int(s['quarter_start']), int(s['quarter_end'])
        ref, trigger, stop, atr = (float(s[x]) for x in ('raw_entry_1s', 'signal_close', 'stop_price', 'atr'))
        imb, btc, eth = float(s['one_imbalance']), float(o['btc_change']), float(o['eth_change'])
        if side not in (-1, 1) or count < 3 or not start <= decision < end or end - start != 900000:
            return None
        if not all(math.isfinite(v) for v in (ref, trigger, stop, atr, imb, btc, eth)) or min(ref, trigger, stop, atr) <= 0:
            return None
        distance = side * (ref - stop) / ref
        if distance <= 0:
            return None
        return [imb, math.log1p(count), side * (ref - trigger) / atr, distance, (decision - start) / 900000, side, btc, eth]
    except (KeyError, ValueError, TypeError, OverflowError, ZeroDivisionError):
        return None


def load(year, frozen):
    if year == '2023':
        base, oi = P / '第七十三轮_二零二三扩展核验/2023基础冻结结果', P / '第七十三轮_二零二三扩展核验/2023持仓量冻结结果'
    else:
        base, oi = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结', P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
    assert sha(base / '完整快照哈希.json') == frozen['base_snapshots'][year] and sha(oi / '冻结哈希.json') == frozen['oi_snapshots'][year]
    bm, om = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8')), json.loads((oi / '冻结哈希.json').read_text(encoding='utf-8'))
    sig, ledger, summary = base / 'batch/动态池逐笔信号筛查.parquet', base / 'batch/动态池单位收益与风险.parquet', base / f'support/{year}一秒观察对照.json'
    for rel, file in [('batch/动态池逐笔信号筛查.parquet', sig), ('batch/动态池单位收益与风险.parquet', ledger), (f'support/{year}一秒观察对照.json', summary)]:
        assert sha(file) == bm['files'][rel]
    oi_file = oi / f'{year}一秒观察持仓量逐笔.csv'
    assert sha(oi_file) == om['files'][oi_file.name]
    signals = {x['observation_id']: x for x in pq.read_table(sig).to_pylist()}
    paths = [x for x in pq.read_table(ledger).to_pylist() if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False]
    with oi_file.open(encoding='utf-8', newline='') as f:
        ois = {(r['observation_id'], r['variant']): r for r in csv.DictReader(f)}
    assert set(ois) == {(r['observation_id'], r['variant']) for r in paths}
    records = []
    for r in paths:
        s, o = signals[r['observation_id']], ois[(r['observation_id'], r['variant'])]
        assert int(s['decision_ts']) == int(r['decision_ts']) and int(r['entry_ts']) >= int(s['entry_exec_ts']) + 1000
        assert near(o['net'], r['net_per_unit_notional'], 1e-11)
        records.append({'year': year, 'observation_id': r['observation_id'], 'variant': r['variant'], 'features': feature(s, o),
                        'net': float(r['net_per_unit_notional']), 'decision_ts': int(s['decision_ts']),
                        'entry_ts': int(r['entry_ts']), 'exit_ts': int(r['exit_ts'])})
    return records, json.loads(summary.read_text(encoding='utf-8'))['rows']


def objective(beta, x, y):
    design = np.column_stack((np.ones(len(x)), x))
    z = design @ beta
    p = sigmoid(z)
    loss = float(np.mean(np.logaddexp(0, z) - y * z) + .05 * np.dot(beta[1:], beta[1:]))
    grad = design.T @ (p - y) / len(y)
    grad[1:] += .1 * beta[1:]
    w = p * (1 - p)
    hessian = (design.T * w) @ design / len(y) + np.diag([0.] + [.1] * x.shape[1])
    return loss, grad, hessian


def newton(x, y):
    beta = np.zeros(x.shape[1] + 1)
    for _ in range(100):
        loss, grad, hessian = objective(beta, x, y)
        if np.max(np.abs(grad)) < 1e-10:
            return beta
        step = np.linalg.solve(hessian, grad)
        scale = 1.
        for _ in range(50):
            candidate = beta - scale * step
            if objective(candidate, x, y)[0] <= loss:
                beta = candidate
                break
            scale *= .5
        else:
            raise AssertionError('independent optimizer did not descend')
    raise AssertionError('independent optimizer did not converge')


def calc_stats(rows, unknown):
    vals = [r['net'] for r in rows]
    n, wins = len(vals), sum(v > 0 for v in vals)
    pos, neg = math.fsum(v for v in vals if v > 0), -math.fsum(v for v in vals if v < 0)
    days = {datetime.fromtimestamp(r['entry_ts'] / 1000, timezone.utc).date() for r in rows}
    return {'known_trades': n, 'net_wins': wins, 'net_win_rate_pct': 100 * wins / n if n else None,
            'mean_net_pct_notional': 100 * math.fsum(vals) / n if n else None,
            'profit_factor': pos / neg if neg else None, 'active_utc_days': len(days), 'unknown_candidates': unknown}


def main():
    path = H / '滚动模型对照.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert result['plan_sha256'] == sha(H / '冻结研究方案.md') == frozen['plan_sha256']
    assert result['model_code_sha256'] == sha(H / 'walkforward_model.py') and result['run_code_sha256'] == sha(H / 'run_walkforward.py')
    model_path, train_path, test_path = H / '滚动模型参数.json', H / '滚动训练明细.csv', H / '滚动评分明细.csv'
    for file, key in [(model_path, 'models_sha256'), (train_path, 'train_detail_sha256'), (test_path, 'test_detail_sha256')]:
        assert sha(file) == result[key]
    fitted = json.loads(model_path.read_text(encoding='utf-8'))['models']
    with train_path.open(encoding='utf-8', newline='') as f:
        train_details = list(csv.DictReader(f))
    with test_path.open(encoding='utf-8', newline='') as f:
        test_details = list(csv.DictReader(f))
    datasets, baselines = {}, {}
    for y in ('2023', '2024', '2026'):
        datasets[y], baselines[y] = load(y, frozen)
    total_checked = 0
    for year, train_years in [('2024', ('2023',)), ('2026', ('2023', '2024'))]:
        for lev in (10, 20):
            variant = f'one_observation_2r_{lev}x'
            train_all = [r for y in train_years for r in datasets[y] if r['variant'] == variant]
            training = [r for r in train_all if r['features'] is not None]
            testing = [r for r in datasets[year] if r['variant'] == variant]
            assert max(r['exit_ts'] for r in training) < min(r['decision_ts'] for r in testing)
            td = {(r['source_year'], r['observation_id']): r for r in train_details if r['test_year'] == year and int(r['leverage']) == lev}
            vd = {r['observation_id']: r for r in test_details if r['test_year'] == year and int(r['leverage']) == lev}
            assert set(td) == {(r['year'], r['observation_id']) for r in training} and set(vd) == {r['observation_id'] for r in testing}
            for r in training:
                s = td[(r['year'], r['observation_id'])]
                assert int(s['decision_ts']) == r['decision_ts'] and int(s['exit_ts']) == r['exit_ts'] and near(s['net'], r['net'])
                assert all(near(s[name], value) for name, value in zip(FEATURES, r['features']))
            x, returns = np.asarray([r['features'] for r in training], float), np.asarray([r['net'] for r in training], float)
            mean, std = x.mean(axis=0), x.std(axis=0)
            std = np.where(std > 1e-12, std, 1.)
            xs = np.clip((x - mean) / std, -5, 5)
            y = (returns > 0).astype(float)
            meta = next(m for m in fitted if m['test_year'] == year and m['leverage'] == lev)
            assert meta['feature_names'] == FEATURES and meta['training_rows'] == len(training) and meta['training_wins'] == int(y.sum())
            assert np.allclose(meta['mean'], mean, rtol=0, atol=1e-12) and np.allclose(meta['std'], std, rtol=0, atol=1e-12)
            beta = np.asarray(meta['beta'])
            loss, gradient, _ = objective(beta, xs, y)
            independently_fit = newton(xs, y)
            assert np.max(np.abs(gradient)) < 1e-6 and np.max(np.abs(independently_fit - beta)) < 1e-5 and near(loss, meta['objective'])
            win, nonwin = float(returns[returns > 0].mean()), float(returns[returns <= 0].mean())
            threshold = -nonwin / (win - nonwin)
            assert near(win, meta['mean_win_fraction']) and near(nonwin, meta['mean_nonwin_fraction']) and near(threshold, meta['breakeven_probability'])
            selected, missing, rejected = [], 0, 0
            for r in testing:
                d = vd[r['observation_id']]
                assert int(d['decision_ts']) == r['decision_ts'] and int(d['entry_ts']) == r['entry_ts'] and int(d['exit_ts']) == r['exit_ts'] and near(d['net'], r['net'])
                if r['features'] is None:
                    assert d['status'] == 'unknown_feature' and d['selected'] == ''
                    missing += 1
                    continue
                assert all(near(d[name], value) for name, value in zip(FEATURES, r['features']))
                z = np.clip((np.asarray(r['features']) - mean) / std, -5, 5)
                probability = float(sigmoid(beta[0] + z @ beta[1:]))
                expected = probability * win + (1 - probability) * nonwin
                assert near(d['probability'], probability) and near(d['expected_net_fraction'], expected)
                assert d['selected'] == str(expected > 0) and d['status'] == 'scored'
                if expected > 0:
                    selected.append(r)
                else:
                    rejected += 1
                total_checked += 1
            ref = next(x for x in baselines[year] if x['leverage'] == lev)
            report = next(x for x in result['rows'] if x['test_year'] == year and x['leverage'] == lev)
            unknown = ref['one_second_observation']['unknown'] + missing
            assert report['train_rows'] == len(training) and report['train_wins'] == int(y.sum())
            assert report['scored'] == len(testing) - missing and report['model_rejected'] == rejected
            assert report['known_no_order'] == ref['known_no_order'] + rejected
            assert len(selected) + unknown + report['known_no_order'] == ref['candidate_events']
            for name, expected in [('baseline', calc_stats(testing, ref['one_second_observation']['unknown'])), ('model', calc_stats(selected, unknown))]:
                for key, value in expected.items():
                    assert near(report[name][key], value), (year, lev, name, key)
    assert total_checked == result['future_test_rows_perturbed']
    audit = {'all_checks_pass': True, 'models_checked': len(fitted), 'scored_test_paths_checked': total_checked,
             'independent_newton_optima_match': True, 'chronology_checked': True,
             'result_sha256': sha(path), 'audit_code_sha256': sha(Path(__file__)),
             'note': 'Time-ordered retrospective analysis; past project exposure means not independent OOS.'}
    (H / '滚动模型独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WALKFORWARD_AUDIT', len(fitted), total_checked, flush=True)


if __name__ == '__main__':
    main()
