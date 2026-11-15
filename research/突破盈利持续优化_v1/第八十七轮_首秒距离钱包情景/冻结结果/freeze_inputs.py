import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    out_path = H / '冻结时点.json'
    assert not out_path.exists()
    files = {
        'r79_freeze': P / '第七十九轮_完成周线趋势/冻结时点.json',
        'r81_complete_snapshot': P / '第八十一轮_八至十月一秒观察/冻结结果/冻结哈希.json',
        'r82_detail': P / '第八十二轮_八至十月持仓量过滤/四时段持仓量已核验逐笔.csv',
        'r85_freeze': P / '第八十五轮_共享资金条件模拟/冻结结果/冻结哈希.json',
        'r85_audit_code': P / '第八十五轮_共享资金条件模拟/audit_wallet.py',
        'r85_engine': P / '第八十五轮_共享资金条件模拟/wallet_simulator.py',
        'r85_test': P / '第八十五轮_共享资金条件模拟/钱包时序合成核验.json',
        'r85_summary': P / '第八十五轮_共享资金条件模拟/共享钱包情景汇总.json',
        'r85_audit': P / '第八十五轮_共享资金条件模拟/共享钱包独立核验.json',
        'r86_freeze': P / '第八十六轮_首秒追价距离过滤/冻结结果/冻结哈希.json',
        'r86_detail': P / '第八十六轮_首秒追价距离过滤/首秒距离逐笔.csv',
        'r86_summary': P / '第八十六轮_首秒追价距离过滤/首秒距离跨期对照.json',
        'r86_audit': P / '第八十六轮_首秒追价距离过滤/首秒距离独立核验.json'}
    for key in ('r85_audit', 'r86_audit'):
        assert json.loads(files[key].read_text(encoding='utf-8'))['all_checks_pass']
    out = {'plan_sha256': sha(H / '冻结研究方案.md'), 'sources_sha256': {k: sha(v) for k, v in files.items()},
           'source_paths': {k: str(v) for k, v in files.items()}, 'frozen_utc': datetime.now(timezone.utc).isoformat(),
           'note': 'Fixed wallet rules after observing the extension gate historical unit results.'}
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT87_FREEZE', sha(out_path), flush=True)


if __name__ == '__main__':
    main()
