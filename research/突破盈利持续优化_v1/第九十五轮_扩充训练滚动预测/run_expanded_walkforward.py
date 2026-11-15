"""Apply the prior fixed model with 2022 added to chronological training."""
import csv
from datetime import datetime, timezone
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
sys.path.insert(0, str(R77)); import walkforward_model as model
import run_walkforward as old
sys.path.insert(0, str(R90)); import replay_2022 as guard

CASES = [('2023', ('2022',)), ('2024', ('2022', '2023')),
         ('2026', ('2022', '2023', '2024')), ('2026_aug_oct', ('2022', '2023', '2024'))]


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def oi_by_event(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    events = {x['observation_id']: x for x in data['events']}
    points = {(x['symbol'], int(x['ts'])): x for x in data['points']}
    result = {}
    for obs, e in events.items():
        v = {}
        for sym, tag in [('BTCUSDT', 'btc'), ('ETHUSDT', 'eth')]:
            a, b = (points.get((sym, int(e[k]))) for k in ('oi_t0', 'oi_previous'))
            if not a or not b or a['status'] != 'verified' or b['status'] != 'verified': break
            current, prior = Decimal(a['official_values'][0]), Decimal(b['official_values'][0])
            assert prior > 0 and current > 0
            v[tag + '_change'] = float(current / prior - 1)
        if len(v) == 2: result[obs] = {'oi_status': 'verified', **v}
    return result


def custom_load(period):
    if period == '2022':
        folder = R90 / '一秒回放批次'; oi_file = R90 / '持仓量逐点来源核验.json'
        affected = {x['observation_id'] for x in json.loads((R93 / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))['samples'] if x['status'] != 'agree'}
        rows = pd.read_parquet(folder / '动态池单位收益与风险.parquet')
        rows = rows[rows.holding_rule.eq('original')]
        signals = pd.read_parquet(folder / '动态池逐笔信号筛查.parquet')
    else:
        assert period == '2026_aug_oct'
        folder = R81 / '冻结结果/batch'; oi_file = R82 / '持仓量逐点来源核验.json'; affected = set()
        manifest = json.loads((R81 / '冻结结果/冻结哈希.json').read_text(encoding='utf-8'))
        for name in ('动态池逐笔信号筛查.parquet', '动态池单位收益与风险.parquet'):
            assert sha(folder / name) == manifest['files']['batch/' + name]
        rows = pd.read_parquet(folder / '动态池单位收益与风险.parquet')
        signals = pd.read_parquet(folder / '动态池逐笔信号筛查.parquet')
    signals = signals.set_index('observation_id').to_dict('index')
    oi = oi_by_event(oi_file); result = []
    for r in rows.to_dict('records'):
        if r['observation_id'] in affected or r['status'] != 'verified' or r['risk_status'] != 'verified' or bool(r['liq_proxy']): continue
        s = signals[r['observation_id']]; o = oi.get(r['observation_id'], {'oi_status': 'unknown'})
        assert s['status'] == 'qualified' and int(s['decision_ts']) == int(r['decision_ts'])
        assert int(r['entry_ts']) >= int(s['entry_exec_ts']) + 1000 >= int(s['decision_ts']) + 2000
        result.append({'year': period, 'observation_id': r['observation_id'], 'variant': r['variant'], 'signal': s, 'oi': o,
                       'features': model.features(s, o), 'net': float(r['net_per_unit_notional']),
                       'entry_ts': int(r['entry_ts']), 'exit_ts': int(r['exit_ts'])})
    return result


def prediction_quality(rows, prior):
    scored = [r for r in rows if r['prediction'] is not None]
    if not scored: return {'brier': None, 'constant_brier': None, 'auc': None}
    pairs = [(r['prediction']['probability'], r['net'] > 0) for r in scored]
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    constant = sum((prior - y) ** 2 for _, y in pairs) / len(pairs)
    pos, neg = [p for p, y in pairs if y], [p for p, y in pairs if not y]
    auc = sum(int(a > b) + .5 * int(a == b) for a in pos for b in neg) / (len(pos) * len(neg)) if pos and neg else None
    return {'brier': brier, 'constant_brier': constant, 'auc': auc}


def main():
    guard.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and frozen['seen_historical_results']
    for k, p in frozen['source_paths'].items(): assert sha(Path(p)) == frozen['source_sha256'][k]
    for proof in (R90 / '持仓量逐点独立核验.json', R90 / '风险来源与账本独立核验.json', R90 / '二零二二汇总独立核验.json',
                  R93 / '敏感性独立核验.json', R82 / '持仓量逐点独立核验.json'):
        assert json.loads(proof.read_text(encoding='utf-8'))['all_checks_pass']
    test = json.loads((R77 / '模型合成时序核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['model_code_sha256'] == sha(R77 / 'walkforward_model.py')
    f77 = json.loads((R77 / '冻结时点.json').read_text(encoding='utf-8'))
    datasets, baseline = {}, {}
    datasets['2022'] = custom_load('2022')
    for year in ('2023', '2024', '2026'): datasets[year], baseline[year] = old.load(year, f77)
    datasets['2026_aug_oct'] = custom_load('2026_aug_oct')
    late_summary = json.loads((R81 / '八至十月一秒观察结果.json').read_text(encoding='utf-8'))['rows']
    records, models, scores, training_rows, perturb = [], [], [], [], 0
    for period, train_years in CASES:
      for lev in (10, 20):
        var = f'one_observation_2r_{lev}x'
        train_all = [x for y in train_years for x in datasets[y] if x['variant'] == var]
        test_all = [x for x in datasets[period] if x['variant'] == var]
        assert test_all
        start = min(int(x['signal']['decision_ts']) for x in test_all)
        train = [x for x in train_all if x['features'] is not None and x['exit_ts'] < start]
        excluded_future = sum(x['exit_ts'] >= start for x in train_all)
        fitted = model.fit([x['features'] for x in train], [x['net'] for x in train])
        models.append({'test_period': period, 'leverage': lev, 'train_years': list(train_years),
                       'train_unknown_features': sum(x['features'] is None for x in train_all),
                       'train_exit_not_earlier': excluded_future, 'test_first_decision_ts': start, **fitted})
        for x in train:
            training_rows.append({'test_period': period, 'leverage': lev, 'source_year': x['year'],
                                  'observation_id': x['observation_id'], 'decision_ts': int(x['signal']['decision_ts']),
                                  'exit_ts': x['exit_ts'], 'net': x['net'], **dict(zip(model.FEATURE_NAMES, x['features']))})
        selected, unknown_features, rejected, tested = [], 0, 0, []
        for x in test_all:
            features = x['features']; prediction = model.score(fitted, features) if features is not None else None
            if prediction is None: unknown_features += 1
            else:
                changed = {**x['signal'], 'exit_ts': 0, 'exit_raw': 1e30, 'net_per_unit_notional': -99999.}
                mutated = model.features(changed, {**x['oi'], 'exit_raw': '1e30', 'net': '-99999'})
                assert np.array_equal(features, mutated) and prediction == model.score(fitted, mutated)
                perturb += 1
                if prediction['selected']: selected.append(x)
                else: rejected += 1
            tested.append({**x, 'prediction': prediction})
            scores.append({'test_period': period, 'leverage': lev, 'observation_id': x['observation_id'],
                           'decision_ts': int(x['signal']['decision_ts']), 'entry_ts': x['entry_ts'], 'exit_ts': x['exit_ts'],
                           'net': x['net'], 'status': 'unknown_feature' if prediction is None else 'scored',
                           'selected': None if prediction is None else prediction['selected'],
                           'probability': None if prediction is None else prediction['probability'],
                           'expected_net_fraction': None if prediction is None else prediction['expected_net_fraction'],
                           **(dict(zip(model.FEATURE_NAMES, features)) if features is not None else {k: None for k in model.FEATURE_NAMES})})
        if period == '2026_aug_oct':
            ref = next(x for x in late_summary if x['leverage'] == lev and x['exit_slippage_pct'] == .05)
            base_unknown, base_no_order, candidates, base_count = ref['unknown_candidates'], ref['known_no_order'], ref['candidate_events'], ref['known_trades']
        else:
            ref = next(x for x in baseline[period] if x['leverage'] == lev)
            base_unknown, base_no_order, candidates, base_count = ref['one_second_observation']['unknown'], ref['known_no_order'], ref['candidate_events'], ref['one_second_observation']['trades']
        assert len(test_all) == base_count and len(selected) + base_unknown + unknown_features + base_no_order + rejected == candidates
        stat = {'test_period': period, 'leverage': lev, 'train_years': list(train_years), 'train_rows': len(train),
                'train_wins': fitted['training_wins'], 'training_breakeven_probability': fitted['breakeven_probability'],
                'scored': len(test_all) - unknown_features, 'feature_unknown': unknown_features, 'model_rejected': rejected,
                'known_no_order': base_no_order + rejected, 'candidate_events': candidates,
                'baseline': old.stats(test_all, base_unknown), 'model': old.stats(selected, base_unknown + unknown_features),
                'prediction_quality': prediction_quality(tested, fitted['training_wins'] / fitted['training_rows'])}
        records.append(stat)
    assert perturb == sum(x['scored'] for x in records)
    for name, fields, data in [('滚动训练明细.csv', ['test_period', 'leverage', 'source_year', 'observation_id', 'decision_ts', 'exit_ts', 'net', *model.FEATURE_NAMES], training_rows),
                               ('滚动评分明细.csv', ['test_period', 'leverage', 'observation_id', 'decision_ts', 'entry_ts', 'exit_ts', 'net', 'status', 'selected', 'probability', 'expected_net_fraction', *model.FEATURE_NAMES], scores)]:
        with (H / name).open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(data)
    model_file = H / '滚动模型参数.json'
    model_file.write_text(json.dumps({'models': models}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    out = {'rows': records, 'future_test_rows_perturbed': perturb, 'frozen_sha256': sha(H / '冻结时点.json'),
           'model_sha256': sha(R77 / 'walkforward_model.py'), 'model_parameters_sha256': sha(model_file),
           'train_detail_sha256': sha(H / '滚动训练明细.csv'), 'score_detail_sha256': sha(H / '滚动评分明细.csv'),
           'code_sha256': sha(Path(__file__)), 'note': 'Retrospective chronological experiment with prior exposure; not blind or account results.'}
    (H / '扩充训练滚动结果.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT95_WALKFORWARD', json.dumps([x for x in records if x['leverage'] == 20], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
