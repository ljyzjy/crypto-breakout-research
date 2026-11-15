"""Freeze the audited, retrospective walk-forward study."""
import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    result_path = H / '滚动模型对照.json'
    audit = json.loads((H / '滚动模型独立核验.json').read_text(encoding='utf-8'))
    quality = json.loads((H / '预测质量独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(result_path) and audit['models_checked'] == 4
    assert quality['all_checks_pass'] and quality['diagnostic_sha256'] == sha(H / '预测质量事后诊断.json')
    names = ['冻结研究方案.md', '冻结时点.json', 'walkforward_model.py', 'test_walkforward_model.py', '模型合成时序核验.json',
             'run_walkforward.py', '滚动模型参数.json', '滚动训练明细.csv', '滚动评分明细.csv', '滚动模型对照.json',
             'audit_walkforward.py', '滚动模型独立核验.json', 'diagnose_prediction_quality.py', '预测质量事后诊断.json',
             'audit_prediction_quality.py', '预测质量独立核验.json', 'freeze_walkforward.py']
    dest = H / '冻结结果'
    dest.mkdir(exist_ok=True)
    files = {}
    for name in names:
        src, target = H / name, dest / name
        digest = sha(src)
        if target.exists():
            assert sha(target) == digest
        else:
            shutil.copyfile(src, target)
            assert sha(target) == digest
        files[name] = digest
    out = {'all_checks_pass': True, 'files': files,
           'note': 'Retrospective model over previously explored periods; no account or live execution validation.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WALKFORWARD_FREEZE', len(files), flush=True)


if __name__ == '__main__':
    main()
