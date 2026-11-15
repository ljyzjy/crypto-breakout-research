"""Fixed, L2-regularized logistic model using only pre-entry features."""
import math
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

LAMBDA = .1
FEATURE_NAMES = ['one_imbalance', 'log_one_count', 'directional_first_second_extension_atr',
                 'directional_stop_distance', 'quarter_elapsed_fraction', 'side', 'btc_oi_change', 'eth_oi_change']


def features(signal, oi):
    try:
        if oi.get('oi_status') != 'verified':
            return None
        side = int(signal['side'])
        count = int(signal['one_count'])
        decision, start, end = int(signal['decision_ts']), int(signal['quarter_start']), int(signal['quarter_end'])
        ref, trigger, stop, atr = (float(signal[x]) for x in ('raw_entry_1s', 'signal_close', 'stop_price', 'atr'))
        imbalance = float(signal['one_imbalance'])
        btc, eth = float(oi['btc_change']), float(oi['eth_change'])
        if side not in (-1, 1) or count < 3 or not start <= decision < end or end - start != 900000:
            return None
        if not all(math.isfinite(v) for v in (ref, trigger, stop, atr, imbalance, btc, eth)) or min(ref, trigger, stop, atr) <= 0:
            return None
        stop_distance = side * (ref - stop) / ref
        if stop_distance <= 0:
            return None
        values = np.asarray([imbalance, math.log1p(count), side * (ref - trigger) / atr, stop_distance,
                             (decision - start) / 900000, side, btc, eth], dtype=float)
        return values if np.isfinite(values).all() else None
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None


def objective(beta, x, y):
    z = beta[0] + x @ beta[1:]
    err = expit(z) - y
    loss = np.mean(np.logaddexp(0., z) - y * z) + .5 * LAMBDA * np.dot(beta[1:], beta[1:])
    gradient = np.r_[np.mean(err), x.T @ err / len(y) + LAMBDA * beta[1:]]
    return float(loss), gradient


def fit(x, returns):
    x = np.asarray(x, dtype=float)
    returns = np.asarray(returns, dtype=float)
    assert x.ndim == 2 and x.shape[1] == len(FEATURE_NAMES) and len(x) == len(returns) and np.isfinite(x).all() and np.isfinite(returns).all()
    y = (returns > 0).astype(float)
    assert len(y) >= 10 and 0 < y.sum() < len(y)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std > 1e-12, std, 1.)
    transformed = np.clip((x - mean) / std, -5., 5.)
    opt = minimize(objective, np.zeros(x.shape[1] + 1), args=(transformed, y), method='L-BFGS-B', jac=True,
                   options={'gtol': 1e-10, 'ftol': 1e-14, 'maxiter': 5000, 'maxls': 50})
    loss, gradient = objective(opt.x, transformed, y)
    if not opt.success or not np.isfinite(opt.x).all() or np.max(np.abs(gradient)) > 1e-6:
        raise RuntimeError('model_fit_unverified')
    win = float(returns[returns > 0].mean())
    nonwin = float(returns[returns <= 0].mean())
    assert win > 0 and nonwin < 0
    return {'feature_names': FEATURE_NAMES, 'mean': mean.tolist(), 'std': std.tolist(), 'beta': opt.x.tolist(),
            'lambda': LAMBDA, 'objective': loss, 'gradient_max_abs': float(np.max(np.abs(gradient))),
            'training_rows': len(y), 'training_wins': int(y.sum()), 'mean_win_fraction': win,
            'mean_nonwin_fraction': nonwin, 'breakeven_probability': -nonwin / (win - nonwin)}


def score(model, x):
    x = np.asarray(x, dtype=float)
    if x.shape != (len(FEATURE_NAMES),) or not np.isfinite(x).all():
        return None
    z = np.clip((x - np.asarray(model['mean'])) / np.asarray(model['std']), -5., 5.)
    probability = float(expit(model['beta'][0] + z @ np.asarray(model['beta'][1:])))
    expected = probability * model['mean_win_fraction'] + (1 - probability) * model['mean_nonwin_fraction']
    return {'probability': probability, 'expected_net_fraction': expected, 'selected': expected > 0}
