"""Freeze the audited 2026 OI gate result before reading 2024 gate outcomes."""
import hashlib
import json
import shutil
from pathlib import Path

H = Path(__file__).resolve().parent
OUT = H / "2026冻结结果"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    point = read(H / "2026持仓量逐点核验.json")
    audit = read(H / "2026持仓量门独立核验.json")
    result_file = H / "2026一秒观察持仓量对照.json"
    results = read(result_file)
    assert point["all_checks_pass"] and point["point_status_counts"] == {"verified": 48}
    assert audit["all_checks_pass"] and audit["result_sha256"] == sha(result_file)
    for lev in (10, 20):
        base = next(r for r in results["rows"] if r["leverage"] == lev and r["strategy"] == "base" and r["exit_slippage_pct"] == 0.05)
        gated = next(r for r in results["rows"] if r["leverage"] == lev and r["strategy"] == "oi_gate" and r["exit_slippage_pct"] == 0.05)
        assert (base["known_trades"], base["net_wins"], base["unknown_candidates"]) == (13, 4, 4)
        assert (gated["known_trades"], gated["net_wins"], gated["unknown_candidates"]) == (5, 3, 4)
    names = ["冻结研究方案.md", "prepare_2026_oi_points.py", "audit_2026_oi_local.py", "evaluate_2026_oi_gate.py", "audit_2026_oi_gate.py", "2026持仓量候选点_待本地复核.json", "2026持仓量逐点核验.json", "2026一秒观察已核验账本.csv", "2026一秒观察持仓量对照.json", "2026一秒观察持仓量逐笔.csv", "2026持仓量门独立核验.json"]
    OUT.mkdir(exist_ok=True)
    files = {}
    for name in names:
        source, dest = H / name, OUT / name
        digest = sha(source)
        if dest.exists():
            assert sha(dest) == digest, name
        else:
            shutil.copyfile(source, dest)
            assert sha(dest) == digest
        files[name] = digest
    info = {"all_checks_pass": True, "year": "2026", "files": files, "base_known": 13, "gate_known": 5, "unknown": 4, "note": "Historical, post-selection exploration; 2024 has not yet been processed under this gate."}
    (OUT / "冻结哈希.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS69_FREEZE_2026", len(files), flush=True)


if __name__ == "__main__":
    main()
