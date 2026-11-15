"""Independently read the six risk ZIPs and verify the extracted rows."""
import csv
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path

H = Path(__file__).resolve().parent
OUT = H / "2026完整风险补验"
ROOT = H.parent.parent.parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-12)


def main():
    manifest_path = OUT / "补充风险来源核验.json"
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["all_checks_pass"] and len(m["archives"]) == 6
    assert m["plan_sha256"] == sha(H / "2026完整风险补验方案.md")
    assert m["code_sha256"] == sha(H / "verify_complete_local_risk_2026.py")
    frozen = OUT / "补验前冻结输入"
    for name, expected in m["pre_supplement_input_sha256"].items():
        assert sha(frozen / name) == expected
    wanted = {}
    pending_ids = {"opening|AVAXUSDT|1777889700000", "opening|NEARUSDT|1779659100000", "opening|BTCUSDT|1782395100000"}
    matched = set()
    for path in (ROOT / "work/oneobs62_2026/tape").glob("*.json"):
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        for row in checkpoint["rows"]:
            if row["observation_id"] not in pending_ids:
                continue
            assert row["observation_id"] not in matched and row["status"] == "qualified"
            matched.add(row["observation_id"])
            assert set(row["paths"]) == {"one_observation_2r_10x", "one_observation_2r_20x"}
            for r in row["paths"].values():
                assert r["status"] == "verified"
                t = int(r["entry_ts"]) // 60000 * 60000
                end = int(r["exit_ts"]) // 60000 * 60000
                while t <= end:
                    import datetime
                    month = datetime.datetime.fromtimestamp(t / 1000, datetime.timezone.utc).strftime("%Y-%m")
                    wanted.setdefault((checkpoint["contract"], month), set()).add(t)
                    t += 60000
    assert matched == pending_ids and len(wanted) == 3
    checked_rows = 0
    for item in m["archives"]:
        source, cache_path = Path(item["source_path"]), Path(item["cache_path"])
        assert sha(source) == item["sha256"] and sha(cache_path) == item["cache_sha256"]
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        assert (cache["kind"], cache["contract"], cache["month"], cache["sha256"]) == (item["kind"], item["contract"], item["month"], item["sha256"])
        needed = wanted[(item["contract"], item["month"])]
        cached = {int(r["ts"]): r for r in cache["rows"]}
        assert len(cached) == len(cache["rows"])
        if item["kind"] == "markPriceKlines":
            assert set(cached) == needed == set(item["required_timestamps"])
        actual = {}
        with zipfile.ZipFile(source) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            assert len(members) == 1
            with z.open(members[0]) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
                for row in reader:
                    key = int(row["open_time"] if item["kind"] == "markPriceKlines" else row["calc_time"])
                    if item["kind"] == "markPriceKlines" and key not in needed:
                        continue
                    assert key not in actual
                    actual[key] = row
        assert set(actual) == set(cached)
        fields = ("open", "high", "low", "close") if item["kind"] == "markPriceKlines" else ("funding_interval_hours", "last_funding_rate")
        for key in actual:
            for field in fields:
                assert near(actual[key][field], cached[key][field]), (item["contract"], key, field)
        checked_rows += len(actual)
    result = {"all_checks_pass": True, "archives_checked": len(m["archives"]), "source_rows_checked": checked_rows, "manifest_sha256": sha(manifest_path), "audit_sha256": sha(Path(__file__)), "note": "Independent ZIP CSV extraction; checksum requests came from verifier and use the same exchange source."}
    (OUT / "补充风险独立核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS62_EXTRA_RISK_AUDIT", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
