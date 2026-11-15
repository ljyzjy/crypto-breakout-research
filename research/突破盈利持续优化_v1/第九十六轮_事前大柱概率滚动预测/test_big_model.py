"""Check that the model trains on completed-candle labels rather than win labels."""
import hashlib
import json
from pathlib import Path

import numpy as np
import run_big_probability as run

H = Path(__file__).resolve().parent


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    rng = np.random.default_rng(126)
    x = rng.normal(size=(40, 8)); y = np.arange(40) % 2 == 0
    x[:, 0] += y.astype(float) * 1.5
    net = np.where(y, -.006, .003)
    fitted = run.fit_big(x, y, net)
    assert fitted['training_rows'] == 40 and fitted['training_big'] == 20
    assert abs(fitted['big_mean_net_fraction'] + .006) < 1e-12 and abs(fitted['other_mean_net_fraction'] - .003) < 1e-12
    pred = run.score(fitted, x[0]); assert 0 < pred['probability'] < 1
    expected = pred['probability'] * -.006 + (1 - pred['probability']) * .003
    assert abs(pred['expected_net_fraction'] - expected) < 1e-12 and pred['selected'] == (expected > 0)
    result = {'all_checks_pass': True, 'tests': ['class_label_independent_of_net_sign', 'conditional_mean_payoff', 'expected_net_rule'],
              'code_sha256': sha(Path(__file__)), 'model_runner_sha256': sha(H / 'run_big_probability.py'),
              'prior_objective_sha256': sha(run.R77 / 'walkforward_model.py')}
    (H / '大柱模型合成核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT96_SYNTHETIC', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
