"""Preserve the finished 2026 candidate replay and its audit artifacts."""
import hashlib
import json
import shutil
from pathlib import Path

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
DEST = H / "2026完整批次_冻结"
BATCH = H / "2026一秒观察分批"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    progress = read(H / "2026一秒观察逐笔进度.json")
    assert progress["processed_groups"] == progress["total_groups"] == 35 and not progress["errors"] and progress["original_unknown"] == 4
    risk = read(BATCH / "动态池单位筛查完整性.json")
    assert risk["risk_statuses"] == {"verified": 26} and risk["risk_cache_missing"] == 0 and risk["liquidation_proxy_paths"] == 0 and risk["tape_incomplete"]
    sample = read(H / "2026一秒观察逐笔独立核验.json")
    ledger_audit = read(H / "2026一秒观察账本独立核验.json")
    assert sample["all_checks_pass"] and len(sample["samples"]) == 5
    assert ledger_audit["all_checks_pass"] and ledger_audit["audited_one_second_observation_paths"] == 26
    summary = read(H / "2026一秒观察对照.json")
    assert all(r["candidate_events"] == 39 and r["one_second_observation"]["trades"] == 13 and r["one_second_observation"]["unknown"] == 4 for r in summary["rows"])
    selected = []
    for name in ["动态池逐笔信号筛查.parquet", "动态池延迟市价路径.parquet", "动态池逐笔提取质量.json", "逐笔执行冻结方案.json", "动态池单位收益与风险.parquet", "动态池单位筛查完整性.json", "动态池风险档案核验清单.json"]:
        selected.append((BATCH / name, Path("batch") / name))
    for name in ["冻结研究方案.md", "run_observation.py", "one_second_observation.py", "2026输入冻结哈希.json", "2026已知候选逐笔来源.json", "2026一秒观察逐笔进度.json", "2026一秒观察对照.json", "2026一秒观察已核验机会.parquet", "2026一秒观察逐笔独立核验.json", "2026一秒观察账本独立核验.json", "2026本地风险来源核验.json", "2026本地风险独立核验.json", "2026完整风险补验方案.md", "verify_complete_local_risk_2026.py", "audit_complete_local_risk_2026.py", "settle_complete_local_risk_2026.py", "audit_ledger_complete_local_2026.py"]:
        selected.append((H / name, Path("support") / name))
    for p in (H / "2026完整风险补验").rglob("*"):
        if p.is_file():
            selected.append((p, Path("extra_risk") / p.relative_to(H / "2026完整风险补验")))
    checkpoints = list((ROOT / "work/oneobs62_2026/tape").glob("*.json"))
    assert len(checkpoints) == 35
    selected += [(p, Path("checkpoints") / p.name) for p in checkpoints]
    assert len({str(x[1]) for x in selected}) == len(selected)
    files = {}
    for source, relative in selected:
        expected = sha(source)
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert sha(target) == expected, str(relative)
        else:
            shutil.copyfile(source, target)
            assert sha(target) == expected
        files[str(relative).replace("\\", "/")] = expected
    manifest = {"all_checks_pass": True, "year": "2026", "known_groups": 35, "original_unknown": 4, "verified_opportunities_per_leverage": 13, "risk_paths": 26, "sample_replays": 5, "files": files, "note": "Frozen unit-opportunity study, not independent OOS or actual fills; source-risk caches and local ZIP paths remain available in the work tree."}
    (DEST / "完整快照哈希.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS62_FREEZE_2026", len(files), "files", flush=True)


if __name__ == "__main__":
    main()
