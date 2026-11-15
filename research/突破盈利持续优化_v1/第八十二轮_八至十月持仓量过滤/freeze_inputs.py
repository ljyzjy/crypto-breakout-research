import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

H = Path(__file__).resolve().parent
R81 = H.parent / '第八十一轮_八至十月一秒观察'
REF = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics')


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    target = H / '冻结时点.json'
    assert not target.exists()
    files = ['冻结时点.json', '一秒回放批次/动态池逐笔信号筛查.parquet',
             '一秒回放批次/动态池延迟市价路径.parquet', '一秒回放批次/动态池单位收益与风险.parquet',
             '一秒回放批次/风险来源与结算.json', '一秒逐笔独立样本核验.json']
    inputs = {name: sha(R81 / name) for name in files}
    assert json.loads((R81 / '一秒逐笔独立样本核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    source = {s: sha(REF / f'{s}-metrics-5m.parquet') for s in ('BTCUSDT', 'ETHUSDT')}
    out = {'plan_sha256': sha(H / '冻结研究方案.md'), 'prior_inputs_sha256': inputs,
           'local_metrics_sha256': source, 'frozen_utc': datetime.now(timezone.utc).isoformat(),
           'note': 'Fixed before viewing period one-second PnL; period was used by other project work.'}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT82_FROZEN', sha(target), flush=True)


if __name__ == '__main__':
    main()
