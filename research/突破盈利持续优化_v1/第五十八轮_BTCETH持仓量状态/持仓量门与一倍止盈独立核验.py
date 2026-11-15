"""Check every combined path and independently aggregate matched 1R/2R outcomes."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import json
import pandas as pd

H = Path(__file__).resolve().parent
R48 = H.parent / "第四十八轮_固定一倍风险止盈"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    detail = H / "持仓量门与一倍止盈逐笔.csv"
    result = H / "持仓量门与一倍止盈组合.json"
    z = json.loads(result.read_text(encoding="utf-8"))
    assert z["detail_sha256"] == sha(detail)
    with detail.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ref = {}
    for year in ("2023", "2024", "2026"):
        data = pd.read_parquet(R48 / f"{year}一倍两倍逐笔配对结果.parquet")
        for x in data.itertuples(index=False):
            ref[(year, int(x.leverage), x.observation_id)] = (float(x.one_r_net), float(x.two_r_net))
    groups = defaultdict(list)
    for r in rows:
        key = (r["year"], int(r["leverage"]), r["observation_id"])
        one, two = ref[key]
        assert abs(float(r["one_r_net"]) - one) < 1e-15 and abs(float(r["two_r_net"]) - two) < 1e-15
        if r["gate"] == "True":
            groups[(key[0], key[1])].append(r)
    count = 0
    for row in z["rows"]:
        g = groups[(row["year"], row["leverage"])]
        for name, field in (("oi_gate_1r", "one_r_net"), ("oi_gate_2r", "two_r_net")):
            values = [Decimal(r[field]) for r in g]
            target = row[name]
            assert len(values) == target["verified_events"] and sum(v > 0 for v in values) == target["wins"]
            assert abs(float(100 * sum(values) / len(values)) - target["mean_net_pct_notional"]) < 1e-12
            loss = -sum(v for v in values if v < 0)
            if loss:
                assert abs(float(sum(v for v in values if v > 0) / loss) - target["profit_factor"]) < 1e-12
            count += 1
    out = {"all_checks_pass": True, "path_pairs_checked": len(rows), "aggregate_groups_checked": count,
           "result_sha256": sha(result), "detail_sha256": sha(detail), "audit_sha256": sha(Path(__file__))}
    (H / "持仓量门与一倍止盈独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
