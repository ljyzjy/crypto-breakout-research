"""Time-ordered prediction of a completed large candle using pre-entry features."""
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

H = Path(__file__).resolve().parent
P = H.parent
R95 = P / '第九十五轮_扩充训练滚动预测'
R77 = P / '第七十七轮_滚动事前模型'
R81 = P / '第八十一轮_八至十月一秒观察'
sys.path.insert(0, str(R95)); import run_expanded_walkforward as prior
import prepare_big_labels as maker
model = prior.model
CASES = prior.CASES


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def fit_big(x, labels, net):
    x, y, net = np.asarray(x, float), np.asarray(labels, float), np.asarray(net, float)
    assert x.ndim == 2 and x.shape[1] == len(model.FEATURE_NAMES) and len(x) >= 10
    assert len(x) == len(y) == len(net) and np.isfinite(x).all() and np.isfinite(net).all() and 0 < y.sum() < len(y)
    mean, std = x.mean(axis=0), x.std(axis=0); std = np.where(std > 1e-12, std, 1.)
    design = np.clip((x - mean) / std, -5., 5.)
    opt = minimize(model.objective, np.zeros(x.shape[1] + 1), args=(design, y), method='L-BFGS-B', jac=True,
                   options={'gtol': 1e-10, 'ftol': 1e-14, 'maxiter': 5000, 'maxls': 50})
    loss, grad = model.objective(opt.x, design, y)
    if not opt.success or not np.isfinite(opt.x).all() or np.max(np.abs(grad)) > 1e-6: raise RuntimeError('model_fit_unverified')
    big_mean, other_mean = float(net[y == 1].mean()), float(net[y == 0].mean())
    return {'feature_names': model.FEATURE_NAMES, 'mean': mean.tolist(), 'std': std.tolist(), 'beta': opt.x.tolist(),
            'lambda': model.LAMBDA, 'objective': loss, 'gradient_max_abs': float(np.max(np.abs(grad))),
            'training_rows': len(y), 'training_big': int(y.sum()), 'big_mean_net_fraction': big_mean,
            'other_mean_net_fraction': other_mean,
            'breakeven_big_probability': -other_mean / (big_mean - other_mean) if big_mean != other_mean else None}


def score(fitted, features):
    z = np.clip((np.asarray(features, float) - np.asarray(fitted['mean'])) / np.asarray(fitted['std']), -5., 5.)
    p = float(expit(fitted['beta'][0] + z @ np.asarray(fitted['beta'][1:])))
    ev = p * fitted['big_mean_net_fraction'] + (1 - p) * fitted['other_mean_net_fraction']
    return {'probability': p, 'expected_net_fraction': ev, 'selected': ev > 0}


def quality(rows, prior_probability):
    vals = [(x['prediction']['probability'], x['label']) for x in rows if x['prediction'] is not None and x['label'] is not None]
    if not vals: return {'known_labels': 0, 'brier': None, 'constant_brier': None, 'auc': None}
    p, y = zip(*vals); pos, neg = [a for a, b in vals if b], [a for a, b in vals if not b]
    return {'known_labels': len(vals), 'brier': math.fsum((a-int(b))**2 for a, b in vals)/len(vals),
            'constant_brier': math.fsum((prior_probability-int(b))**2 for b in y)/len(y),
            'auc': sum(int(a>b)+.5*int(a==b) for a in pos for b in neg)/(len(pos)*len(neg)) if pos and neg else None}


def main():
    prior.guard.guard(start=True)
    test = json.loads((H / '大柱模型合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256'] == sha(H / 'test_big_model.py')
    assert test['model_runner_sha256'] == sha(Path(__file__)) and test['prior_objective_sha256'] == sha(R77 / 'walkforward_model.py')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and frozen['prior_outcomes_and_labels_seen']
    for k, p in frozen['source_paths'].items(): assert sha(Path(p)) == frozen['source_sha256'][k]
    label_path = H / '事后大柱训练标签.parquet'; audit = json.loads((H / '事后大柱标签独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['label_sha256'] == sha(label_path)
    assert audit['code_sha256'] == sha(H / 'audit_big_labels.py')
    labels = {(x['period'], x['observation_id']): x for x in pd.read_parquet(label_path).to_dict('records')}
    data = maker.datasets()
    f77 = json.loads((R77 / '冻结时点.json').read_text(encoding='utf-8'))
    baseline = {y: prior.old.load(y, f77)[1] for y in ('2023', '2024', '2026')}
    late = json.loads((R81 / '八至十月一秒观察结果.json').read_text(encoding='utf-8'))['rows']
    results, models, train_rows, score_rows, perturb = [], [], [], [], 0
    for period, years in CASES:
      for lev in (10, 20):
        variant = f'one_observation_2r_{lev}x'
        train_all = [r for y in years for r in data[y] if r['variant'] == variant]
        testing = [r for r in data[period] if r['variant'] == variant]; assert testing
        first = min(int(r['signal']['decision_ts']) for r in testing)
        train = [r for r in train_all if r['features'] is not None and labels[(r['year'], r['observation_id'])]['status'] == 'verified'
                 and r['exit_ts'] < first and int(labels[(r['year'], r['observation_id'])]['label_available_ts']) < first]
        fitted = fit_big([r['features'] for r in train], [labels[(r['year'], r['observation_id'])]['big_aligned'] for r in train], [r['net'] for r in train])
        models.append({'test_period': period, 'leverage': lev, 'train_years': list(years), 'test_first_decision_ts': first,
                       'training_excluded': len(train_all) - len(train), **fitted})
        for r in train:
            label = labels[(r['year'], r['observation_id'])]
            train_rows.append({'test_period': period, 'leverage': lev, 'source_year': r['year'], 'observation_id': r['observation_id'],
                               'decision_ts': int(r['signal']['decision_ts']), 'exit_ts': r['exit_ts'],
                               'label_available_ts': int(label['label_available_ts']), 'big_aligned': bool(label['big_aligned']),
                               'net': r['net'], **dict(zip(model.FEATURE_NAMES, r['features']))})
        selected, unknown, rejected, tested = [], 0, 0, []
        for r in testing:
            feature = r['features']; pred = score(fitted, feature) if feature is not None else None
            label = labels[(period, r['observation_id'])]
            actual = bool(label['big_aligned']) if label['status'] == 'verified' else None
            if pred is None: unknown += 1
            else:
                changed_signal = {**r['signal'], 'exit_ts': 0, 'exit_raw': 1e30, 'bar_close': 1e30, 'net_per_unit_notional': -99999.}
                changed = model.features(changed_signal, {**r['oi'], 'net': '-99999', 'future_close': '1e30'})
                assert np.array_equal(feature, changed) and pred == score(fitted, changed); perturb += 1
                if pred['selected']: selected.append(r)
                else: rejected += 1
            tested.append({'prediction': pred, 'label': actual})
            score_rows.append({'test_period': period, 'leverage': lev, 'observation_id': r['observation_id'],
                               'decision_ts': int(r['signal']['decision_ts']), 'entry_ts': r['entry_ts'], 'exit_ts': r['exit_ts'],
                               'label_available_ts': int(label['label_available_ts']), 'label_status': label['status'], 'big_aligned': actual,
                               'net': r['net'], 'status': 'unknown_feature' if pred is None else 'scored',
                               'selected': None if pred is None else pred['selected'], 'probability': None if pred is None else pred['probability'],
                               'expected_net_fraction': None if pred is None else pred['expected_net_fraction'],
                               **(dict(zip(model.FEATURE_NAMES, feature)) if feature is not None else {k: None for k in model.FEATURE_NAMES})})
        if period == '2026_aug_oct':
            ref = next(x for x in late if x['leverage'] == lev and x['exit_slippage_pct'] == .05)
            base_unknown, no_order, candidates, count = ref['unknown_candidates'], ref['known_no_order'], ref['candidate_events'], ref['known_trades']
        else:
            ref = next(x for x in baseline[period] if x['leverage'] == lev)
            base_unknown, no_order, candidates, count = ref['one_second_observation']['unknown'], ref['known_no_order'], ref['candidate_events'], ref['one_second_observation']['trades']
        assert len(testing) == count and len(selected) + base_unknown + unknown + no_order + rejected == candidates
        results.append({'test_period': period, 'leverage': lev, 'train_years': list(years), 'train_rows': len(train),
                        'train_big': fitted['training_big'], 'train_big_mean_pct': 100*fitted['big_mean_net_fraction'],
                        'train_other_mean_pct': 100*fitted['other_mean_net_fraction'],
                        'break_even_big_probability': fitted['breakeven_big_probability'], 'scored': len(testing)-unknown,
                        'feature_unknown': unknown, 'model_rejected': rejected, 'known_no_order': no_order+rejected,
                        'candidate_events': candidates, 'baseline': prior.old.stats(testing, base_unknown),
                        'model': prior.old.stats(selected, base_unknown+unknown), 'prediction_quality': quality(tested, fitted['training_big']/len(train))})
    assert perturb == sum(x['scored'] for x in results)
    for name, fields, rows in [('训练明细.csv', ['test_period','leverage','source_year','observation_id','decision_ts','exit_ts','label_available_ts','big_aligned','net',*model.FEATURE_NAMES], train_rows),
                               ('评分明细.csv', ['test_period','leverage','observation_id','decision_ts','entry_ts','exit_ts','label_available_ts','label_status','big_aligned','net','status','selected','probability','expected_net_fraction',*model.FEATURE_NAMES], score_rows)]:
        with (H / name).open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    (H / '模型参数.json').write_text(json.dumps({'models': models}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    out = {'rows': results, 'future_test_rows_perturbed': perturb, 'frozen_sha256': sha(H / '冻结时点.json'),
           'label_sha256': sha(label_path), 'label_audit_sha256': sha(H / '事后大柱标签独立核验.json'),
           'model_parameters_sha256': sha(H / '模型参数.json'), 'train_detail_sha256': sha(H / '训练明细.csv'),
           'score_detail_sha256': sha(H / '评分明细.csv'), 'code_sha256': sha(Path(__file__)),
           'note': 'Retrospective big-candle labels for training, pre-entry features only; no blind/live claims.'}
    (H / '大柱概率滚动结果.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT96_WALKFORWARD', json.dumps([x for x in results if x['leverage']==20], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
