"""Rebuild point-in-time OI from source parquet and independently summarize."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
REF = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics")
OLD = P / "第五十五轮_WorkBuddy资金费假说" / "已核验机会及资金费门.csv"
FAST = P / "第五十一轮_缩短市价入场延迟"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    output_file, detail_file = H / "持仓量门跨期对照.json", H / "持仓量门逐笔机会.csv"
    out = json.loads(output_file.read_text(encoding="utf-8"))
    assert out["detail_sha256"] == sha(detail_file) and out["feature_tests"]["all_checks_pass"]
    with detail_file.open(encoding="utf-8-sig", newline="") as f:
        detail = list(csv.DictReader(f))
    needed = {int(r["feature_ts"]) for r in detail}
    needed |= {x - 3_600_000 for x in list(needed)}
    points = defaultdict(list)
    for sym in ("BTCUSDT", "ETHUSDT"):
        table = pq.read_table(REF / f"{sym}-metrics-5m.parquet", columns=["ts", "sum_open_interest"], use_threads=False)
        times = table["ts"].combine_chunks().cast(pa.int64()).to_numpy(zero_copy_only=False) // 1000
        values = table["sum_open_interest"].combine_chunks().to_numpy(zero_copy_only=False)
        where = np.flatnonzero(np.isin(times, np.asarray(sorted(needed), dtype=np.int64)))
        for i in where:
            points[(sym, int(times[i]))].append(float(values[i]))
        del table, times, values
    with OLD.open(encoding="utf-8-sig", newline="") as f:
        old = {(r["year"], int(r["leverage"]), r["observation_id"]): r for r in csv.DictReader(f)}
    pair = {}
    for year in ("2024", "2026"):
        frame = pd.read_parquet(FAST / f"{year}一秒五秒逐笔配对结果.parquet")
        for r in frame.itertuples(index=False):
            pair[(year, int(r.leverage), r.observation_id)] = (int(r.one_second_entry_ts), float(r.one_second_net))
    groups = defaultdict(list)
    for row in detail:
        year, lev, obs, variant = row["year"], int(row["leverage"]), row["observation_id"], row["variant"]
        expected = old[(year, lev, obs)]
        assert int(row["decision_ts"]) == int(expected["decision_ts"])
        assert int(row["side"]) == int(expected["side"])
        entry, net = ((int(expected["entry_ts"]), float(expected["net_per_unit_notional"])) if variant == "five_second"
                      else pair[(year, lev, obs)])
        assert int(row["entry_ts"]) == entry and abs(float(row["net"]) - net) < 1e-15
        t0 = (int(row["decision_ts"]) - 900_000) // 300_000 * 300_000
        assert int(row["feature_ts"]) == t0 and 900_000 <= int(row["decision_ts"]) - t0 < 1_200_000
        changes = []
        for sym, col in (("BTCUSDT", "btc_oi_change"), ("ETHUSDT", "eth_oi_change")):
            new, prior = points[(sym, t0)], points[(sym, t0 - 3_600_000)]
            if len(new) != 1 or len(prior) != 1 or not all(math.isfinite(v) and v > 0 for v in new + prior):
                changes = None
                break
            value = new[0] / prior[0] - 1
            assert abs(float(row[col]) - value) < 1e-15
            changes.append(value)
        if changes is None:
            assert row["gate"] == "" and row["feature_status"] != "verified"
        else:
            assert (row["gate"] == "True") == all(v > 0 for v in changes)
            assert row["feature_status"] == "verified"
        groups[(year, lev, variant)].append(row)
    checked = 0
    for result in out["rows"]:
        group = groups[(result["year"], result["leverage"], result["variant"])]
        variants = (("baseline", group),
                    ("oi_gate", [r for r in group if r["gate"] == "True"]),
                    ("known_filtered", [r for r in group if r["gate"] == "False"]))
        assert sum(r["gate"] == "" for r in group) == result["additional_feature_unknown"]
        for name, rows in variants:
            vals = [float(r["net"]) for r in rows]
            expected = result[name]
            assert len(vals) == expected["verified_events"] and sum(v > 0 for v in vals) == expected["wins"]
            if vals:
                assert abs(100 * sum(vals) / len(vals) - expected["mean_net_pct_notional"]) < 1e-12
            losses = -sum(v for v in vals if v < 0)
            if losses:
                assert abs(sum(v for v in vals if v > 0) / losses - expected["profit_factor"]) < 1e-12
            days = {datetime.fromtimestamp(int(r["entry_ts"]) / 1000, timezone.utc).date() for r in rows}
            assert len(days) == expected["active_utc_days"]
            checked += 1
    proof = {"all_checks_pass": True, "independent_point_keys": len(points),
             "trade_paths_reconciled": len(detail), "aggregate_groups_checked": checked,
             "output_sha256": sha(output_file), "detail_sha256": sha(detail_file),
             "audit_sha256": sha(Path(__file__)),
             "note": "Re-read source parquet; official comparison is six days, and actual historical release times remain unknown."}
    (H / "持仓量门独立核验.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
