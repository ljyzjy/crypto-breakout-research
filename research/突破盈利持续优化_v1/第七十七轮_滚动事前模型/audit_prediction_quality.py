"""Independently verify AUC via average ranks and Brier-score arithmetic."""
import csv
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '预测质量事后诊断.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    assert report['code_sha256'] == sha(H / 'diagnose_prediction_quality.py')
    result = json.loads((H / '滚动模型对照.json').read_text(encoding='utf-8'))
    assert report['input_result_sha256'] == sha(H / '滚动模型对照.json')
    model_path, detail_path = H / '滚动模型参数.json', H / '滚动评分明细.csv'
    assert result['models_sha256'] == sha(model_path) and result['test_detail_sha256'] == sha(detail_path)
    models = json.loads(model_path.read_text(encoding='utf-8'))['models']
    with detail_path.open(encoding='utf-8', newline='') as f:
        details = list(csv.DictReader(f))
    for r in report['rows']:
        subset = [x for x in details if x['test_year'] == r['test_year'] and int(x['leverage']) == r['leverage'] and x['status'] == 'scored']
        probs = [float(x['probability']) for x in subset]
        labels = [int(float(x['net']) > 0) for x in subset]
        n, pos, neg = len(probs), sum(labels), len(probs) - sum(labels)
        assert r['scored'] == n and r['net_wins'] == pos
        ranked = sorted(zip(probs, labels), key=lambda z: z[0])
        rank_sum, i = 0., 0
        while i < n:
            j = i + 1
            while j < n and ranked[j][0] == ranked[i][0]:
                j += 1
            average_rank = ((i + 1) + j) / 2
            rank_sum += average_rank * sum(y for _, y in ranked[i:j])
            i = j
        auc = (rank_sum - pos * (pos + 1) / 2) / (pos * neg) if pos and neg else None
        meta = next(m for m in models if m['test_year'] == r['test_year'] and m['leverage'] == r['leverage'])
        prior = meta['training_wins'] / meta['training_rows']
        brier = math.fsum((p - y) ** 2 for p, y in zip(probs, labels)) / n if n else None
        constant = math.fsum((prior - y) ** 2 for y in labels) / n if n else None
        assert near(auc, r['auc']) and near(brier, r['brier']) and near(constant, r['training_win_rate_constant_brier'])
        assert near(min(probs) if n else None, r['probability_min']) and near(max(probs) if n else None, r['probability_max'])
    out = {'all_checks_pass': True, 'groups_checked': len(report['rows']), 'diagnostic_sha256': sha(path),
           'audit_code_sha256': sha(Path(__file__))}
    (H / '预测质量独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WALKFORWARD_QUALITY_AUDIT', len(report['rows']), flush=True)


if __name__ == '__main__':
    main()
