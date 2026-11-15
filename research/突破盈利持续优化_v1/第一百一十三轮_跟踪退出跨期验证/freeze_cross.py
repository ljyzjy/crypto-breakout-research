"""Freeze cross-period source snapshots and fixed raw sample IDs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
P = H.parent
R70 = P / "第七十轮_一秒观察一倍止盈"
R112 = P / "第一百一十二轮_突破后跟踪退出"
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(R70))
import replay_1r as previous


def main():
    bulk.runner.guard(start=True)
    test = json.loads((R112 / "跟踪退出合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["engine_sha256"] == bulk.sha(R112 / "trailing.py")
    sources = [H / "研究方案.md", R112 / "trailing.py", R112 / "跟踪退出合成核验.json",
               R70 / "replay_1r.py", R70 / "settle_1r_local.py", R70 / "exit_1r_oneobs.py"]
    years = {}
    for year in ("2024", "2026"):
        tasks, fp, paths, snap = previous.prepare(year)
        ids = sorted({e["observation_id"] for task in tasks for e in task["events"]},
                     key=lambda x: hashlib.sha256(("trailing-cross-v1|" + year + "|" + x).encode()).hexdigest())
        assert len(ids) >= 4
        years[year] = {"prior_fingerprint": fp, "source_snapshot_sha256": snap, "paths": paths,
                       "task_groups": len(tasks), "sample_ids": ids[:4]}
        manifest = P / f"第六十二轮_一秒观察更早突破/{year}完整批次_冻结/完整快照哈希.json"
        one = R70 / f"{year}一倍止盈本地风险账本.json"
        proof = R70 / f"{year}一倍止盈账本独立核验.json"
        verify = json.loads(proof.read_text(encoding="utf-8"))
        assert verify["all_checks_pass"] and verify["ledger_sha256"] == bulk.sha(one)
        sources.extend((manifest, one, proof))
    out = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "years": years,
           "sources": {str(path): bulk.sha(path) for path in sources}, "code_sha256": bulk.sha(Path(__file__)),
           "note": "Fixed historical rule and samples; no claim of independent blind data."}
    (H / "输入冻结.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": True, "years": years}, ensure_ascii=False))


if __name__ == "__main__":
    main()
