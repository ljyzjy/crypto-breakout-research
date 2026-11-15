"""Execute the fixed retrospective yearly walk-forward model."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pyarrow.parquet as pq
import walkforward_model as model

H = Path(__file__).resolve().parent
P = H.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def load(year, frozen):
    if year == '2023':
        base = P / '第七十三轮_二零二三扩展核验/2023基础冻结结果'
        oi = P / '第七十三轮_二零二三扩展核验/2023持仓量冻结结果'
    else:
        base = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结'
        oi = P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
    assert sha(base / '完整快照哈希.json') == frozen['base_snapshots'][year]
    assert sha(oi / '冻结哈希.json') == frozen['oi_snapshots'][year]
    bm = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8'))
    om = json.loads((oi / '冻结哈希.json').read_text(encoding='utf-8'))
    assert bm['all_checks_pass'] and om['all_checks_pass']
    names = ['batch/动态池逐笔信号筛查.parquet', 'batch/动态池单位收益与风险.parquet', f'support/{year}一秒观察对照.json']
    for name in names:
        assert sha(base / name) == bm['files'][name]
    oi_name = f'{year}一秒观察持仓量逐笔.csv'
    assert sha(oi / oi_name) == om['files'][oi_name]
    signals = {x['observation_id']: x for x in pq.read_table(base / names[0]).to_pylist()}
    ledger = [x for x in pq.read_table(base / names[1]).to_pylist() if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False]
    with (oi / oi_name).open(encoding='utf-8', newline='') as f:
        oi_rows = {(r['observation_id'], r['variant']): r for r in csv.DictReader(f)}
    assert set(oi_rows) == {(x['observation_id'], x['variant']) for x in ledger}
    summaries = json.loads((base / names[2]).read_text(encoding='utf-8'))['rows']
    result = []
    for row in ledger:
        obs, var = row['observation_id'], row['variant']
        s, o = signals[obs], oi_rows[(obs, var)]
        assert s['status'] == 'qualified' and int(s['decision_ts']) == int(row['decision_ts'])
        assert int(s['entry_exec_ts']) >= int(s['decision_ts']) + 1000
        assert int(row['entry_ts']) >= int(s['entry_exec_ts']) + 1000
        assert math.isclose(float(o['net']), float(row['net_per_unit_notional']), rel_tol=1e-10, abs_tol=1e-12)
        result.append({'year': year, 'observation_id': obs, 'variant': var, 'signal': s, 'oi': o,
                       'features': model.features(s, o), 'net': float(row['net_per_unit_notional']),
                       'entry_ts': int(row['entry_ts']), 'exit_ts': int(row['exit_ts'])})
    return result, summaries


def stats(rows, unknown):
    vals = [r['net'] for r in rows]
    n, wins = len(vals), sum(v > 0 for v in vals)
    positive, negative = math.fsum(v for v in vals if v > 0), -math.fsum(v for v in vals if v < 0)
    days = {datetime.fromtimestamp(r['entry_ts'] / 1000, timezone.utc).date() for r in rows}
    return {'known_trades': n, 'net_wins': wins, 'net_win_rate_pct': 100 * wins / n if n else None,
            'mean_net_pct_notional': 100 * math.fsum(vals) / n if n else None,
            'profit_factor': positive / negative if negative else None, 'active_utc_days': len(days),
            'unknown_candidates': unknown}


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    test = json.loads((H / '模型合成时序核验.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == frozen['plan_sha256'] == test['plan_sha256']
    assert test['all_checks_pass'] and test['model_code_sha256'] == sha(H / 'walkforward_model.py')
    assert test['test_code_sha256'] == sha(H / 'test_walkforward_model.py')
    datasets, baseline = {}, {}
    for year in ('2023', '2024', '2026'):
        datasets[year], baseline[year] = load(year, frozen)
    results, models, train_detail, test_detail, perturbations = [], [], [], [], 0
    for test_year, train_years in [('2024', ('2023',)), ('2026', ('2023', '2024'))]:
        for lev in (10, 20):
            variant = f'one_observation_2r_{lev}x'
            train_all = [r for year in train_years for r in datasets[year] if r['variant'] == variant]
            training = [r for r in train_all if r['features'] is not None]
            testing = [r for r in datasets[test_year] if r['variant'] == variant]
            assert max(r['exit_ts'] for r in training) < min(r['signal']['decision_ts'] for r in testing)
            fitted = model.fit([r['features'] for r in training], [r['net'] for r in training])
            repeat = model.fit([r['features'] for r in training], [r['net'] for r in training])
            assert np.allclose(fitted['beta'], repeat['beta'], rtol=0, atol=1e-12)
            models.append({'test_year': test_year, 'leverage': lev, 'train_years': list(train_years),
                           'train_unknown_features': len(train_all) - len(training), **fitted})
            for r in training:
                train_detail.append({'test_year': test_year, 'leverage': lev, 'source_year': r['year'],
                                     'observation_id': r['observation_id'], 'decision_ts': int(r['signal']['decision_ts']),
                                     'exit_ts': r['exit_ts'], 'net': r['net'], **dict(zip(model.FEATURE_NAMES, r['features']))})
            selected, feature_unknown, rejected = [], 0, 0
            for r in testing:
                features = r['features']
                if features is None:
                    feature_unknown += 1
                    prediction = None
                else:
                    prediction = model.score(fitted, features)
                    changed_signal = {**r['signal'], 'exit_ts': 0, 'exit_raw': 1e30, 'net_per_unit_notional': -99999.}
                    changed_oi = {**r['oi'], 'exit_raw': '1e30', 'net': '-99999', 'future_close': '1e30'}
                    altered = model.features(changed_signal, changed_oi)
                    assert np.array_equal(features, altered) and prediction == model.score(fitted, altered)
                    perturbations += 1
                    if prediction['selected']:
                        selected.append(r)
                    else:
                        rejected += 1
                feature_fields = dict(zip(model.FEATURE_NAMES, features)) if features is not None else {k: None for k in model.FEATURE_NAMES}
                test_detail.append({'test_year': test_year, 'leverage': lev, 'observation_id': r['observation_id'],
                                    'decision_ts': int(r['signal']['decision_ts']), 'entry_ts': r['entry_ts'], 'exit_ts': r['exit_ts'],
                                    'net': r['net'], 'status': 'unknown_feature' if prediction is None else 'scored',
                                    'selected': None if prediction is None else prediction['selected'],
                                    'probability': None if prediction is None else prediction['probability'],
                                    'expected_net_fraction': None if prediction is None else prediction['expected_net_fraction'], **feature_fields})
            ref = next(x for x in baseline[test_year] if x['leverage'] == lev)
            assert len(testing) == ref['one_second_observation']['trades']
            unknown = ref['one_second_observation']['unknown'] + feature_unknown
            no_order = ref['known_no_order'] + rejected
            assert len(selected) + unknown + no_order == ref['candidate_events']
            result = {'test_year': test_year, 'leverage': lev, 'train_years': list(train_years),
                      'train_rows': len(training), 'train_wins': fitted['training_wins'],
                      'train_unknown_features': len(train_all) - len(training), 'scored': len(testing) - feature_unknown,
                      'model_rejected': rejected, 'breakeven_probability': fitted['breakeven_probability'],
                      'known_no_order': no_order, 'candidate_events': ref['candidate_events'],
                      'baseline': stats(testing, ref['one_second_observation']['unknown']),
                      'model': stats(selected, unknown)}
            results.append(result)
    assert perturbations == sum(x['scored'] for x in results)
    train_fields = ['test_year', 'leverage', 'source_year', 'observation_id', 'decision_ts', 'exit_ts', 'net', *model.FEATURE_NAMES]
    test_fields = ['test_year', 'leverage', 'observation_id', 'decision_ts', 'entry_ts', 'exit_ts', 'net', 'status',
                   'selected', 'probability', 'expected_net_fraction', *model.FEATURE_NAMES]
    for name, fields, records in [('滚动训练明细.csv', train_fields, train_detail), ('滚动评分明细.csv', test_fields, test_detail)]:
        with (H / name).open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
    models_path = H / '滚动模型参数.json'
    models_path.write_text(json.dumps({'models': models}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    out = {'rows': results, 'future_test_rows_perturbed': perturbations, 'plan_sha256': sha(H / '冻结研究方案.md'),
           'frozen_sha256': sha(H / '冻结时点.json'), 'model_code_sha256': sha(H / 'walkforward_model.py'),
           'run_code_sha256': sha(Path(__file__)), 'models_sha256': sha(models_path),
           'train_detail_sha256': sha(H / '滚动训练明细.csv'), 'test_detail_sha256': sha(H / '滚动评分明细.csv'),
           'note': 'Retrospective time-ordered exploration on previously used years; no live arrival or account validation.'}
    (H / '滚动模型对照.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in results:
        if row['leverage'] == 20:
            print('WALKFORWARD_RESULT', json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
