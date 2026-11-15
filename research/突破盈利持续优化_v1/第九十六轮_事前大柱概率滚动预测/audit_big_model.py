"""Rebuild large-candle model with independent Newton optimization and causal labels."""
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R95 = P / '第九十五轮_扩充训练滚动预测'
R77 = P / '第七十七轮_滚动事前模型'
R81 = P / '第八十一轮_八至十月一秒观察'
sys.path.insert(0, str(R95)); import audit_expanded_walkforward as independent
sys.path.insert(0, str(R77)); import audit_walkforward as scalar
FEATURES = scalar.FEATURES
CASES = independent.CASES


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b, tol=1e-9):
    if a is None or b is None: return a is b
    return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)


def quality(scored, probability):
    if not scored: return {'known_labels': 0, 'brier': None, 'constant_brier': None, 'auc': None}
    pos, neg = [p for p, y in scored if y], [p for p, y in scored if not y]
    return {'known_labels': len(scored), 'brier': math.fsum((p-int(y))**2 for p,y in scored)/len(scored),
            'constant_brier': math.fsum((probability-int(y))**2 for p,y in scored)/len(scored),
            'auc': sum(int(a>b)+.5*int(a==b) for a in pos for b in neg)/(len(pos)*len(neg)) if pos and neg else None}


def main():
    independent.guard.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for k, p in frozen['source_paths'].items(): assert sha(Path(p)) == frozen['source_sha256'][k]
    path = H / '大柱概率滚动结果.json'; result = json.loads(path.read_text(encoding='utf-8'))
    assert result['frozen_sha256'] == sha(H / '冻结时点.json') and result['code_sha256'] == sha(H / 'run_big_probability.py')
    for f, k in [('事后大柱训练标签.parquet','label_sha256'), ('事后大柱标签独立核验.json','label_audit_sha256'),
                 ('模型参数.json','model_parameters_sha256'), ('训练明细.csv','train_detail_sha256'), ('评分明细.csv','score_detail_sha256')]:
        assert sha(H / f) == result[k]
    assert json.loads((H / '事后大柱标签独立核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    assert json.loads((H / '大柱模型合成核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    labels = {(x['period'], x['observation_id']): x for x in pd.read_parquet(H / '事后大柱训练标签.parquet').to_dict('records')}
    datasets = {'2022': independent.custom_load('2022'), '2026_aug_oct': independent.custom_load('2026_aug_oct')}
    f77 = json.loads((R77 / '冻结时点.json').read_text(encoding='utf-8')); base = {}
    for period in ('2023', '2024', '2026'): datasets[period], base[period] = scalar.load(period, f77)
    late = json.loads((R81 / '八至十月一秒观察结果.json').read_text(encoding='utf-8'))['rows']
    models = json.loads((H / '模型参数.json').read_text(encoding='utf-8'))['models']
    with (H / '训练明细.csv').open(encoding='utf-8', newline='') as f: train_details = list(csv.DictReader(f))
    with (H / '评分明细.csv').open(encoding='utf-8', newline='') as f: score_details = list(csv.DictReader(f))
    checked = 0
    for period, years in CASES:
      for lev in (10, 20):
        variant = f'one_observation_2r_{lev}x'; testing = [r for r in datasets[period] if r['variant'] == variant]
        first = min(r['decision_ts'] for r in testing)
        train_all = [r for y in years for r in datasets[y] if r['variant'] == variant]
        train = [r for r in train_all if r['features'] is not None and labels[(r['year'],r['observation_id'])]['status'] == 'verified'
                 and r['exit_ts'] < first and int(labels[(r['year'],r['observation_id'])]['label_available_ts']) < first]
        x = np.asarray([r['features'] for r in train], float)
        y = np.asarray([bool(labels[(r['year'],r['observation_id'])]['big_aligned']) for r in train], float)
        returns = np.asarray([r['net'] for r in train], float)
        mean, std = x.mean(axis=0), x.std(axis=0); std = np.where(std > 1e-12, std, 1.)
        beta = scalar.newton(np.clip((x - mean) / std, -5., 5.), y)
        bmean, omean = float(returns[y==1].mean()), float(returns[y==0].mean())
        meta = next(z for z in models if z['test_period'] == period and z['leverage'] == lev)
        assert meta['training_rows'] == len(train) and meta['training_big'] == int(y.sum())
        assert meta['training_excluded'] == len(train_all) - len(train) and meta['test_first_decision_ts'] == first
        assert np.allclose(meta['mean'], mean, rtol=1e-10, atol=1e-10) and np.allclose(meta['std'], std, rtol=1e-10, atol=1e-10)
        assert np.allclose(meta['beta'], beta, rtol=1e-5, atol=1e-5)
        assert near(meta['big_mean_net_fraction'], bmean, 1e-11) and near(meta['other_mean_net_fraction'], omean, 1e-11)
        threshold = -omean / (bmean-omean) if bmean != omean else None
        assert near(meta['breakeven_big_probability'], threshold, 1e-11)
        observed_train = {(z['source_year'],z['observation_id']): z for z in train_details if z['test_period']==period and z['leverage']==str(lev)}
        assert len(observed_train) == len(train)
        for r in train:
            z = observed_train[(r['year'],r['observation_id'])]; label = labels[(r['year'],r['observation_id'])]
            assert int(z['decision_ts']) == r['decision_ts'] and int(z['exit_ts']) == r['exit_ts'] < first
            assert int(z['label_available_ts']) == int(label['label_available_ts']) < first
            assert z['big_aligned'] == str(bool(label['big_aligned'])) and near(z['net'],r['net'],1e-11)
            assert all(near(z[k], v, 1e-10) for k,v in zip(FEATURES,r['features']))
        observed = {z['observation_id']:z for z in score_details if z['test_period']==period and z['leverage']==str(lev)}
        assert len(observed) == len(testing)
        selected, scored_labels, unknown, rejected = [], [], 0, 0
        for r in testing:
            z = observed[r['observation_id']]; label = labels[(period,r['observation_id'])]
            assert int(z['decision_ts']) == r['decision_ts'] and int(z['entry_ts']) == r['entry_ts'] and int(z['exit_ts']) == r['exit_ts']
            assert int(z['label_available_ts']) == int(label['label_available_ts']) and z['label_status'] == label['status']
            assert near(z['net'],r['net'],1e-11)
            if r['features'] is None:
                assert z['status'] == 'unknown_feature'; unknown += 1; continue
            assert all(near(z[k],v,1e-10) for k,v in zip(FEATURES,r['features']))
            transformed = np.clip((np.asarray(r['features'])-mean)/std,-5.,5.)
            p = float(scalar.sigmoid(beta[0] + transformed @ beta[1:])); ev = p*bmean + (1-p)*omean
            assert near(z['probability'],p,1e-5) and near(z['expected_net_fraction'],ev,1e-6) and z['selected'] == str(ev > 0)
            if label['status'] == 'verified':
                assert z['big_aligned'] == str(bool(label['big_aligned'])); scored_labels.append((p,bool(label['big_aligned'])))
            if ev > 0: selected.append(r)
            else: rejected += 1
            checked += 1
        out = next(z for z in result['rows'] if z['test_period']==period and z['leverage']==lev)
        assert out['train_rows'] == len(train) and out['train_big'] == int(y.sum()) and out['scored'] == len(testing)-unknown
        assert out['feature_unknown'] == unknown and out['model_rejected'] == rejected
        assert near(out['train_big_mean_pct'],100*bmean,1e-10) and near(out['train_other_mean_pct'],100*omean,1e-10)
        if period == '2026_aug_oct':
            ref = next(z for z in late if z['leverage']==lev and z['exit_slippage_pct']==.05)
            u, no, candidates = ref['unknown_candidates'], ref['known_no_order'], ref['candidate_events']
        else:
            ref = next(z for z in base[period] if z['leverage']==lev)
            u, no, candidates = ref['one_second_observation']['unknown'], ref['known_no_order'], ref['candidate_events']
        assert len(selected)+u+unknown+no+rejected == candidates == out['candidate_events'] and out['known_no_order'] == no+rejected
        for k,v in scalar.calc_stats(testing,u).items(): assert near(out['baseline'][k],v)
        for k,v in scalar.calc_stats(selected,u+unknown).items(): assert near(out['model'][k],v)
        for k,v in quality(scored_labels,int(y.sum())/len(y)).items(): assert near(out['prediction_quality'][k],v,1e-5)
    assert checked == result['future_test_rows_perturbed']
    output = {'all_checks_pass': True, 'model_groups_checked': len(result['rows']), 'scored_paths_checked': checked,
              'result_sha256': sha(path), 'code_sha256': sha(Path(__file__)), 'independent_optimizer_sha256': sha(R77 / 'audit_walkforward.py'),
              'note': 'Training labels complete before test; historical test periods were already explored and execution remains a proxy.'}
    (H / '大柱概率模型独立核验.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT96_AUDIT', json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
