"""Compare low-memory sequential reads with two already completed groups."""
import hashlib
import json
import math
from pathlib import Path

import run_observation as runner

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-9)
    return a == b


def main():
    year = "2024"
    candidates, baseline, paths, proof = runner.inputs(year)
    fp = runner.fingerprint(year)
    current = ROOT / "work/oneobs62_2024/tape"
    isolated = ROOT / "work/oneobs62_2024_stream_parity/tape"
    isolated.mkdir(parents=True, exist_ok=True)
    d = candidates[candidates.observation_id.isin(proof)]
    tasks = [(sym, day, bool(n), group.to_dict("records")) for (sym, day, n), group in d.groupby(["contract", "day", "needs_next"])]
    choices = []
    for spec in tasks:
        path = current / (runner.key(fp, spec) + ".json")
        if not path.exists():
            continue
        cp = json.loads(path.read_text(encoding="utf-8"))
        size = sum(int(a.get("bytes", 0)) for a in cp["archives"] if a["kind"] == "aggTrades")
        choices.append((size, spec, path, cp))
    choices.sort(key=lambda x: (x[0], str(x[2])))
    selected = []
    for status in ("qualified", "flow_filter_not_met"):
        entry = next((x for x in choices if any(r["status"] == status for r in x[3]["rows"]) and x[2] not in {q[2] for q in selected}), None)
        assert entry is not None, status
        selected.append(entry)
    runner.public_range.MAX_BUFFER = 0
    runner.public_range.WORKERS = 1
    checked = []
    for _, spec, original_path, original in selected:
        fresh = runner.task(year, fp, spec, baseline, paths, proof, isolated)
        assert fresh["status"] == original["status"] == "verified"
        for key in ("contract", "day", "needs_next", "rows"):
            assert same(original[key], fresh[key]), (key, original_path.name)
        def arch(z):
            return [{k: a.get(k) for k in ("kind", "day", "sha256", "bytes", "windows")} for a in z["archives"]]
        assert same(arch(original), arch(fresh)), original_path.name
        isolated_file = isolated / original_path.name
        checked.append({"contract": spec[0], "day": spec[1], "statuses": [r["status"] for r in original["rows"]], "original_checkpoint_sha256": sha(original_path), "stream_checkpoint_sha256": sha(isolated_file), "events": len(original["rows"])})
        print("OBS62_STREAM_PARITY", len(checked), "/", len(selected), flush=True)
    result = {"all_checks_pass": True, "year": year, "runner_fingerprint": fp, "plan_sha256": sha(H / "2024低内存读取方案.md"), "test_sha256": sha(Path(__file__)), "runner_sha256": sha(H / "run_observation.py"), "range_sha256": sha(H.parent / "第四十八轮_固定一倍风险止盈/public_range.py"), "stream_sha256": sha(H.parent / "第四十七轮_一次重新突破确认/public_tape_stream.py"), "samples": checked, "note": "Both routes use the same archive SHA and parser; separate successful and rejected groups independently re-read."}
    (H / "2024低内存顺序读取核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS62_STREAM_PARITY_PASS", len(checked), flush=True)


if __name__ == "__main__":
    main()
