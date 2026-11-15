"""Post-hoc AUC and Brier checks for all scored walk-forward candidates."""
import csv
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    result_path = H / '滚动模型对照.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    models_path, details_path = H / '滚动模型参数.json', H / '滚动评分明细.csv'
    assert result['models_sha256'] == sha(models_path) and result['test_detail_sha256'] == sha(details_path)
    audit = json.loads((H / '滚动模型独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(result_path)
    models = json.loads(models_path.read_text(encoding='utf-8'))['models']
    with details_path.open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    output = []
    for year in ('2024', '2026'):
        for lev in (10, 20):
            group = [r for r in rows if r['test_year'] == year and int(r['leverage']) == lev and r['status'] == 'scored']
            meta = next(x for x in models if x['test_year'] == year and x['leverage'] == lev)
            prior = meta['training_wins'] / meta['training_rows']
            predictions = [(float(r['probability']), float(r['net']) > 0) for r in group]
            positives = [p for p, y in predictions if y]
            negatives = [p for p, y in predictions if not y]
            n = len(predictions)
            auc = (sum(int(a > b) + .5 * int(a == b) for a in positives for b in negatives) / (len(positives) * len(negatives))) if positives and negatives else None
            brier = sum((p - int(y)) ** 2 for p, y in predictions) / n if n else None
            constant = sum((prior - int(y)) ** 2 for _, y in predictions) / n if n else None
            output.append({'test_year': year, 'leverage': lev, 'scored': n, 'net_wins': len(positives), 'auc': auc,
                           'brier': brier, 'training_win_rate_constant_brier': constant,
                           'probability_min': min((p for p, _ in predictions), default=None),
                           'probability_max': max((p for p, _ in predictions), default=None),
                           'breakeven_probability': meta['breakeven_probability']})
    out = {'rows': output, 'input_result_sha256': sha(result_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Descriptive prediction diagnostics in previously studied periods, not a blind calibration test.'}
    (H / '预测质量事后诊断.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for r in output:
        if r['leverage'] == 20:
            print('WALKFORWARD_QUALITY', r, flush=True)


if __name__ == '__main__':
    main()
