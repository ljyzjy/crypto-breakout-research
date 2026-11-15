"""Use the existing 2023 source/risk engine with the 2.2 GB reserve intact."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import psutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
R62 = P / '第六十二轮_一秒观察更早突破'
OLD = P / '第四十三轮_旧十一币2023年复核'
sys.path.insert(0, str(R62))
sys.path.insert(0, str(OLD))
import run_observation as runner
import settle_local_2023_serial as local


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    runner.inputs('2023')
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert runner.fingerprint('2023') == frozen['runner_fingerprint']
    assert json.loads((OLD / '本地风险来源串行合成核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    risk = json.loads((OLD / '风险来源冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(OLD / '冻结研究方案.md') == risk['plan_sha256']
    assert all(sha(Path(x['path'])) == x['sha256'] for x in risk['sources'].values())
    original = (P / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py').read_text(encoding='utf-8')
    copy = (OLD / 'settle_2023_serial_engine.py').read_text(encoding='utf-8').replace('max_workers=1', 'max_workers=2')
    assert original[:original.index("    end=int(pd.Timestamp('2024-05-01'")] == copy[:copy.index("    print('OLD11_2023_RISK_COMPLETE'")]
    engine, old_task = local.engine, local.local_task
    batch = R62 / '2023一秒观察分批'
    names = ['动态池逐笔信号筛查.parquet', '动态池延迟市价路径.parquet', '动态池逐笔提取质量.json', '逐笔执行冻结方案.json']
    inputs = {n: sha(batch / n) for n in names}
    (batch / '风险输入哈希.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8')
    local.WORK.mkdir(parents=True, exist_ok=True)
    engine.HERE, engine.WORK = batch, local.WORK

    def guarded(z):
        while psutil.virtual_memory().available < 850 * 1024 ** 2:
            if shutil.disk_usage(ROOT).free < 2_200_000_000:
                return {'kind': z[0], 'contract': z[1], 'month': z[2], 'status': 'error', 'error': 'disk_headroom', 'rows': []}
            time.sleep(3)
        if shutil.disk_usage(ROOT).free < 2_200_000_000:
            return {'kind': z[0], 'contract': z[1], 'month': z[2], 'status': 'error', 'error': 'disk_headroom', 'rows': []}
        return old_task(z)

    engine.task = guarded
    print('YEAR2023_RISK_BEGIN', flush=True)
    engine.main()
    assert all(sha(batch / n) == value for n, value in inputs.items())
    print('YEAR2023_RISK_END', flush=True)


if __name__ == '__main__':
    main()
