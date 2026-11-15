"""Freeze the finished 2024 candidate replay and independent audits."""
import hashlib
import json
import shutil
from pathlib import Path

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
DEST = H / "2024完整批次_冻结"
BATCH = H / "2024一秒观察分批"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    progress = read(H / "2024一秒观察逐笔进度.json")
    assert progress["processed_groups"] == progress["total_groups"] == 95 and not progress["errors"] and progress["original_unknown"] == 16
    quality = read(BATCH / "动态池逐笔提取质量.json")
    assert quality["candidate_events"] == 119
    sample = read(H / "2024一秒观察逐笔独立核验.json")
    audit = read(H / "2024一秒观察账本独立核验.json")
    assert sample["all_checks_pass"] and len(sample["samples"]) >= 3 and audit["all_checks_pass"]
    local_audit = H / "2024本地风险来源独立核验.json"
    if (H / "2024本地风险来源记录.jsonl").exists():
        local = read(local_audit)
        assert local["all_checks_pass"] and local["journal_sha256"] == sha(H / "2024本地风险来源记录.jsonl")
        assert local["settlement_code_sha256"] == sha(H / "settle_2024_local_sources.py")
        assert local["audit_code_sha256"] == sha(H / "audit_2024_local_sources.py")
    summary = read(H / "2024一秒观察对照.json")
    assert len(summary["rows"]) == 2 and all(r["candidate_events"] == 119 and r["one_second_observation"]["unknown"] >= 16 for r in summary["rows"])
    selected = []
    for name in ["动态池逐笔信号筛查.parquet", "动态池延迟市价路径.parquet", "动态池逐笔提取质量.json", "逐笔执行冻结方案.json", "动态池单位收益与风险.parquet", "动态池单位筛查完整性.json", "动态池风险档案核验清单.json"]:
        selected.append((BATCH / name, Path("batch") / name))
    for name in ["冻结研究方案.md", "run_observation.py", "one_second_observation.py", "2024输入冻结哈希.json", "2024已知候选逐笔来源.json", "2024一秒观察逐笔进度.json", "2024一秒观察对照.json", "2024一秒观察已核验机会.parquet", "2024一秒观察逐笔独立核验.json", "2024一秒观察账本独立核验.json"]:
        selected.append((H / name, Path("support") / name))
    for name in ["2024低内存读取方案.md", "test_2024_stream_reader.py", "2024低内存顺序读取核验.json", "run_2024_streaming.py", "2024低内存顺序读取运行记录.jsonl", "verify_2024_interrupted_checkpoints.py", "2024中断后检查点核验.json", "2024自适应分段读取方案.md", "test_2024_adaptive_ranges.py", "2024自适应分段读取核验.json", "run_2024_adaptive_ranges.py", "2024自适应分段运行记录.jsonl"]:
        p = H / name
        if p.exists():
            selected.append((p, Path("support") / name))
    for name in ["2024本地风险结算方案.md", "settle_2024_local_sources.py", "test_2024_local_sources.py", "2024本地风险读取对照核验.json", "2024本地风险来源记录.jsonl", "audit_2024_local_sources.py", "2024本地风险来源独立核验.json"]:
        p = H / name
        if p.exists():
            selected.append((p, Path("support") / name))
    for p in (H / "2024冻结输入").rglob("*"):
        if p.is_file():
            selected.append((p, Path("input") / p.relative_to(H / "2024冻结输入")))
    checkpoints = list((ROOT / "work/oneobs62_2024/tape").glob("*.json"))
    assert len(checkpoints) == 95
    selected += [(p, Path("checkpoints") / p.name) for p in checkpoints]
    assert len({str(x[1]) for x in selected}) == len(selected)
    files = {}
    for source, relative in selected:
        digest = sha(source)
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert sha(target) == digest, str(relative)
        else:
            shutil.copyfile(source, target)
            assert sha(target) == digest
        files[str(relative).replace("\\", "/")] = digest
    manifest = {"all_checks_pass": True, "year": "2024", "known_groups": 95, "original_unknown": 16, "risk_paths_checked": audit["audited_one_second_observation_paths"], "sample_replays": len(sample["samples"]), "files": files, "note": "Historical unit opportunities, not independent OOS or actual fills. Missing source or risk candidates remain unknown."}
    (DEST / "完整快照哈希.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS62_FREEZE_2024", len(files), "files", flush=True)


if __name__ == "__main__":
    main()
