"""Synthetic gradient, timing, missing-input and future-field invariance tests."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import approx_fprime
import walkforward_model as model

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    rng = np.random.default_rng(9371)
    x = rng.normal(size=(48, len(model.FEATURE_NAMES)))
    returns = np.where(x[:, 0] + .3 * x[:, 2] > .05, .004, -.003)
    beta = rng.normal(size=x.shape[1] + 1)
    y = (returns > 0).astype(float)
    _, gradient = model.objective(beta, x, y)
    numerical = approx_fprime(beta, lambda b: model.objective(b, x, y)[0], 1e-7)
    assert np.max(np.abs(gradient - numerical)) < 1e-6
    fit = model.fit(x, returns)
    assert fit['gradient_max_abs'] < 1e-6 and 0 < fit['breakeven_probability'] < 1
    signal = {'side': 1, 'one_count': 10, 'decision_ts': 100000, 'quarter_start': 0, 'quarter_end': 900000,
              'raw_entry_1s': 100.1, 'signal_close': 100., 'stop_price': 99.4, 'atr': 2., 'one_imbalance': .5,
              'future_exit_price': 110., 'future_net_return': .1}
    oi = {'oi_status': 'verified', 'btc_change': .01, 'eth_change': -.01}
    a = model.features(signal, oi)
    assert a is not None and len(a) == 8 and np.isfinite(a).all()
    changed = {**signal, 'future_exit_price': 1., 'future_net_return': -.9, 'future_close': 9999.}
    b = model.features(changed, oi)
    assert np.array_equal(a, b) and model.score(fit, a) == model.score(fit, b)
    assert model.features(signal, {**oi, 'oi_status': 'unknown_oi'}) is None
    assert model.features({**signal, 'one_count': 2}, oi) is None
    assert model.features({**signal, 'decision_ts': 900000}, oi) is None
    result = {'all_checks_pass': True, 'gradient_max_difference': float(np.max(np.abs(gradient - numerical))),
              'fit_gradient_max_abs': fit['gradient_max_abs'], 'future_fields_do_not_change_features_or_score': True,
              'invalid_inputs_remain_unknown': True, 'model_code_sha256': sha(H / 'walkforward_model.py'),
              'plan_sha256': sha(H / '冻结研究方案.md'), 'test_code_sha256': sha(Path(__file__))}
    (H / '模型合成时序核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WALKFORWARD_SYNTHETIC_PASS', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
