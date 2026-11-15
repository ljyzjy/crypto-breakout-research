"""Independent Decimal aggregation of fixed audited exit stress paths."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import json

H = Path(__file__).resolve().parent
STRESS = H.parent / "第五十九轮_退出滑点压力"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    with (H / "持仓量门逐笔机会.csv").open(encoding="utf-8-sig", newline="") as f:
        keep = {(r["year"], int(r["leverage"]), r["observation_id"])
                for r in csv.DictReader(f) if r["variant"] == "one_second" and r["gate"] == "True"}
    groups = defaultdict(list)
    with (STRESS / "退出滑点压力逐笔.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            key = (r["year"], int(r["leverage"]), r["observation_id"])
            if key in keep:
                groups[(r["year"], int(r["leverage"]), Decimal(r["exit_slip"]) * 100)].append(Decimal(r["net"]))
    output_file = H / "持仓量门退出滑点压力.json"
    rows = json.loads(output_file.read_text(encoding="utf-8"))["rows"]
    for r in rows:
        vals = groups[(r["year"], r["leverage"], Decimal(str(r["exit_slippage_pct"])))]
        assert len(vals) == r["verified_events"] and sum(v > 0 for v in vals) == r["wins"]
        assert abs(float(Decimal(100) * sum(vals) / len(vals)) - r["mean_net_pct_notional"]) < 1e-12
        loss = -sum(v for v in vals if v < 0)
        if loss:
            assert abs(float(sum(v for v in vals if v > 0) / loss) - r["profit_factor"]) < 1e-12
    out = {"all_checks_pass": True, "scenario_groups": len(rows),
           "result_sha256": sha(output_file), "audit_sha256": sha(Path(__file__)),
           "note": "Scenario path prices and fees were independently audited in round 59."}
    (H / "持仓量门退出滑点压力独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
