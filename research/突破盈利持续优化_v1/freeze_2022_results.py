"""Copy finished 2022 research artifacts to an isolated D: snapshot and hash every file."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

P = Path(__file__).resolve().parent
ROOT = P.parent.parent
R90 = P / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
ROUNDS = {
    '90': ('第九十轮_二零二二公开行情', ['二零二二汇总独立核验.json', '共享钱包独立核验.json']),
    '91': ('第九十一轮_突破柱前五分钟过滤', ['前五分钟过滤独立核验.json', '共享钱包独立核验.json']),
    '92': ('第九十二轮_突破柱收益分解', ['突破柱分解独立核验.json']),
    '93': ('第九十三轮_原始逐笔抽样交叉核验', ['原始逐笔独立核验.json', '敏感性独立核验.json', '前五分钟敏感性独立核验.json', '突破柱敏感性独立核验.json', '共享钱包独立核验.json']),
    '94': ('第九十四轮_零成交分钟排名补充', ['零成交小时独立核验.json', '替代排名候选独立核验.json', '替代口径结果独立核验.json']),
    '95': ('第九十五轮_扩充训练滚动预测', ['扩充滚动模型独立核验.json']),
    '96': ('第九十六轮_事前大柱概率滚动预测', ['事后大柱标签独立核验.json', '大柱概率模型独立核验.json']),
    '97': ('第九十七轮_原始逐笔一秒回放试点', ['原始逐笔试点独立核验.json']),
    '98': ('第九十八轮_二零二二原始逐笔全样本', ['原始逐笔独立抽样核验.json', '风险来源与账本独立核验.json', '原始逐笔汇总独立核验.json', '共享钱包独立核验.json']),
    '99': ('第九十九轮_成本相对波幅门', ['过滤结果独立核验.json', '共享钱包独立核验.json']),
    '100': ('第一百轮_突破无进展提前退出', ['进展退出独立核验.json', '进展退出汇总独立核验.json', '共享钱包独立核验.json']),
    '101': ('第一百零一轮_成本门历史跨期核查', ['成本门跨期独立核验.json']),
    '102': ('第一百零二轮_大柱持有损益核查', ['大柱标签独立核验.json', '大柱对照独立核验.json']),
    '103': ('第一百零三轮_计划风险超额诊断', ['风险超额独立核验.json']),
}


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def freeze(which):
    name, proofs = ROUNDS[which]; folder = P / name
    for p in proofs:
        assert json.loads((folder / p).read_text(encoding='utf-8'))['all_checks_pass'], p
    target = runner.ROOT / 'frozen_results' / name
    target.mkdir(parents=True, exist_ok=True)
    assert target.resolve().is_relative_to(runner.ROOT.resolve())
    rows = []
    for file in sorted(folder.rglob('*')):
        if not file.is_file() or file.suffix.lower() not in ('.py', '.json', '.md', '.csv', '.parquet'):
            continue
        rel = file.relative_to(folder)
        if any(part in ('冻结结果', '__pycache__') for part in rel.parts): continue
        runner.guard()
        dst = target / rel
        assert dst.resolve().is_relative_to(target.resolve())
        dst.parent.mkdir(parents=True, exist_ok=True)
        digest = sha(file)
        if dst.exists():
            assert sha(dst) == digest, f'existing_snapshot_differs:{rel}'
        else:
            shutil.copy2(file, dst)
        assert sha(dst) == digest
        rows.append({'relative_path': rel.as_posix(), 'bytes': file.stat().st_size, 'sha256': digest})
    local = folder / '冻结结果'; local.mkdir(exist_ok=True)
    manifest = {'all_checks_pass': True, 'snapshot_root': str(target), 'files': rows,
                'file_count': len(rows), 'proofs': proofs, 'snapshot_script_sha256': sha(Path(__file__)),
                'note': 'File-integrity snapshot only; strategy results retain unknowns, retrospective bias and execution limits.'}
    (local / '冻结哈希.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT_FREEZE', which, len(rows), str(target), flush=True)


def main():
    runner.guard(start=True)
    assert len(sys.argv) >= 2 and all(x in ROUNDS for x in sys.argv[1:])
    for which in sys.argv[1:]: freeze(which)


if __name__ == '__main__':
    main()
