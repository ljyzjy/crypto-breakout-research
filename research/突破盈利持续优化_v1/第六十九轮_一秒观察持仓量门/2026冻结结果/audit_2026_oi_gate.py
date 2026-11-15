"""Independent OI timing, selection, cost and label accounting audit."""
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math

H = Path(__file__).resolve().parent
P = H.parent
BIG = P / "第五十八轮_BTCETH持仓量状态/大柱捕捉事后明细.csv"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def close(a, b):
    return (a is None and b is None) or (a is not None and b is not None and math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10))


def compute_gate(decision, points):
    point_time = ((decision - 900000) // 300000) * 300000
    assert 900000 <= decision - point_time < 1200000
    changes = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        newer = points.get((symbol, point_time))
        older = points.get((symbol, point_time - 3600000))
        if not newer or not older or newer["status"] != "verified" or older["status"] != "verified":
            return None
        if len(newer["values"]) != 1 or len(older["values"]) != 1:
            return None
        x, y = float(newer["values"][0]), float(older["values"][0])
        if not math.isfinite(x) or not math.isfinite(y) or min(x, y) <= 0:
            return None
        changes.append(x > y)
    return all(changes)


def main():
    result_file = H / "2026一秒观察持仓量对照.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    points_file = H / "2026持仓量逐点核验.json"
    ledger_file = H / "2026一秒观察已核验账本.csv"
    detail_file = H / "2026一秒观察持仓量逐笔.csv"
    point_audit = json.loads(points_file.read_text(encoding="utf-8"))
    assert sha(points_file) == result["inputs"]["point_audit_sha256"] and sha(ledger_file) == result["inputs"]["ledger_csv_sha256"]
    assert sha(H / "冻结研究方案.md") == result["inputs"]["plan_sha256"] and sha(BIG) == result["inputs"]["postclose_bar_labels_sha256"]
    points = {(x["symbol"], int(x["ts"])): x for x in point_audit["points"]}
    ledger = read_csv(ledger_file)
    detail = read_csv(detail_file)
    assert len(ledger) == len(detail) == 26
    index = {(r["observation_id"], r["variant"]): r for r in ledger}
    assert len(index) == 26
    labels = {(r["contract"], int(r["quarter_start"]), int(r["allowed_side"])) for r in read_csv(BIG) if r["year"] == "2026" and r["leverage"] == "20" and r["variant"] == "one_second"}
    assert len(labels) == 9
    for r in detail:
        old = index[(r["observation_id"], r["variant"])]
        decision = int(r["decision_ts"])
        assert decision == int(float(old["decision_ts"]))
        gate = compute_gate(decision, points)
        assert (r["gate"] == "True") if gate is True else (r["gate"] == "False") if gate is False else not r["gate"]
        assert int(r["oi_t0"]) == ((decision - 900000) // 300000) * 300000 and int(r["oi_previous"]) == int(r["oi_t0"]) - 3600000
        assert close(r["net"], old["net_per_unit_notional"])
        symbol = r["observation_id"].split("|")[1]
        is_big = (symbol, decision // 900000 * 900000, int(float(r["side"]))) in labels
        assert (r["post_close_big"] == "True") == is_big
    checked = 0
    for row in result["rows"]:
        lev, strategy, slip = row["leverage"], row["strategy"], row["exit_slippage_pct"] / 100
        universe = [r for r in detail if r["variant"].endswith(f"_{lev}x")]
        selected = [r for r in universe if strategy == "base" or r["gate"] == "True"]
        extra_unknown = sum(not r["gate"] for r in universe) if strategy != "base" else 0
        assert row["unknown_candidates"] == 4 + extra_unknown
        vals = []
        for r in selected:
            entry, raw, side = float(r["entry_fill"]), float(r["exit_raw"]), int(float(r["side"]))
            exit_ = raw * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r["funding"]))
        n, wins = len(vals), sum(v > 0 for v in vals)
        assert row["known_trades"] == n and row["net_wins"] == wins
        assert close(row["mean_net_pct_notional"], 100 * math.fsum(vals) / n if n else None)
        pos = math.fsum(v for v in vals if v > 0)
        neg = -math.fsum(v for v in vals if v < 0)
        assert close(row["profit_factor"], pos / neg if neg else None)
        assert row["postclose_big_captured"] == sum(r["post_close_big"] == "True" for r in selected)
        checked += len(vals)
    result_sha = sha(result_file)
    out = {"all_checks_pass": True, "groups_checked": len(result["rows"]), "repeated_scenario_paths_checked": checked, "input_ledger_rows_checked": len(ledger), "oi_points_checked": len(points), "post_close_bar_labels_checked": len(labels), "result_sha256": result_sha, "audit_code_sha256": sha(Path(__file__)), "note": "Independent arithmetic and point-in-time checks on already audited historical sources; not live publication or account validation."}
    (H / "2026持仓量门独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS69_AUDIT", json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
