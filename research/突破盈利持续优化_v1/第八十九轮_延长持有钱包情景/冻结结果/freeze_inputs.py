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
    target = H / '冻结时点.json'
    assert not target.exists()
    files = {'r79_freeze': P / '第七十九轮_完成周线趋势/冻结时点.json',
             'r81_complete_snapshot': P / '第八十一轮_八至十月一秒观察/冻结结果/冻结哈希.json',
             'r82_detail': P / '第八十二轮_八至十月持仓量过滤/四时段持仓量已核验逐笔.csv',
             'r85_engine': P / '第八十五轮_共享资金条件模拟/wallet_simulator.py',
             'r85_test': P / '第八十五轮_共享资金条件模拟/钱包时序合成核验.json',
             'r85_audit_code': P / '第八十五轮_共享资金条件模拟/audit_wallet.py',
             'r85_summary': P / '第八十五轮_共享资金条件模拟/共享钱包情景汇总.json',
             'r85_audit': P / '第八十五轮_共享资金条件模拟/共享钱包独立核验.json',
             'r86_detail': P / '第八十六轮_首秒追价距离过滤/首秒距离逐笔.csv',
             'r86_audit': P / '第八十六轮_首秒追价距离过滤/首秒距离独立核验.json',
             'r87_summary': P / '第八十七轮_首秒距离钱包情景/首秒距离钱包情景汇总.json',
             'r87_audit': P / '第八十七轮_首秒距离钱包情景/首秒距离钱包独立核验.json',
             'r88_snapshot': P / '第八十八轮_延长一根柱持有/冻结结果/冻结哈希.json',
             'r88_ledger': P / '第八十八轮_延长一根柱持有/延长持有风险账本.json',
             'r88_summary': P / '第八十八轮_延长一根柱持有/延长持有配对汇总.json',
             'r88_audit': P / '第八十八轮_延长一根柱持有/延长持有配对独立核验.json'}
    for k in ('r85_audit', 'r86_audit', 'r87_audit', 'r88_audit'):
        assert json.loads(files[k].read_text(encoding='utf-8'))['all_checks_pass']
    out = {'plan_sha256': sha(H / '冻结研究方案.md'), 'source_paths': {k: str(v) for k, v in files.items()},
           'sources_sha256': {k: sha(v) for k, v in files.items()}, 'frozen_utc': datetime.now(timezone.utc).isoformat(),
           'note': 'Fixed known-path wallet comparison after observing extended-exit unit outcomes.'}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT89_FREEZE', sha(target), flush=True)


if __name__ == '__main__':
    main()
