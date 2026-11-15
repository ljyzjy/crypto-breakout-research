"""Independent accounting and known-time gate audit for the 2024 paths."""
from pathlib import Path
import hashlib
import json
import math

from audit_2026_oi_gate import close, compute_gate, read_csv, sha

H = Path(__file__).resolve().parent
P = H.parent
BIG = P / "第五十八轮_BTCETH持仓量状态/大柱捕捉事后明细.csv"
SNAP = P / "第六十二轮_一秒观察更早突破/2024完整批次_冻结"


def main():
    result_file = H / "2024一秒观察持仓量对照.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    points_file = H / "2024持仓量逐点核验.json"
    ledger_file = H / "2024一秒观察已核验账本.csv"
    detail_file = H / "2024一秒观察持仓量逐笔.csv"
    audit = json.loads(points_file.read_text(encoding="utf-8"))
    assert sha(points_file) == result["inputs"]["point_audit_sha256"] and sha(ledger_file) == result["inputs"]["ledger_csv_sha256"]
    assert sha(H / "冻结研究方案.md") == result["inputs"]["plan_sha256"] and sha(BIG) == result["inputs"]["postclose_bar_labels_sha256"]
    points = {(x["symbol"], int(x["ts"])): x for x in audit["points"]}
    ledger, detail = read_csv(ledger_file), read_csv(detail_file)
    assert ledger and len(ledger) == len(detail)
    index = {(r["observation_id"], r["variant"]): r for r in ledger}
    assert len(index) == len(ledger)
    labels = {(r["contract"], int(r["quarter_start"]), int(r["allowed_side"])) for r in read_csv(BIG) if r["year"] == "2024" and r["leverage"] == "20" and r["variant"] == "one_second"}
    assert len(labels) == 22
    baseline = json.loads((SNAP / "support/2024一秒观察对照.json").read_text(encoding="utf-8"))["rows"]
    for r in detail:
        old = index[(r["observation_id"], r["variant"])]
        decision = int(r["decision_ts"])
        assert decision == int(float(old["decision_ts"]))
        gate = compute_gate(decision, points)
        assert (r["gate"] == "True") if gate is True else (r["gate"] == "False") if gate is False else not r["gate"]
        assert int(r["oi_t0"]) == ((decision - 900000) // 300000) * 300000 and int(r["oi_previous"]) == int(r["oi_t0"]) - 3600000
        assert close(r["net"], old["net_per_unit_notional"])
        symbol = r["observation_id"].split("|")[1]
        big = (symbol, decision // 900000 * 900000, int(float(r["side"]))) in labels
        assert (r["post_close_big"] == "True") == big
    checked = 0
    for row in result["rows"]:
        lev, strategy, slip = row["leverage"], row["strategy"], row["exit_slippage_pct"] / 100
        universe = [r for r in detail if r["variant"].endswith(f"_{lev}x")]
        chosen = [r for r in universe if strategy == "base" or r["gate"] == "True"]
        extra_unknown = sum(not r["gate"] for r in universe) if strategy == "oi_gate" else 0
        ref = next(x for x in baseline if x["leverage"] == lev)
        assert row["unknown_candidates"] == ref["one_second_observation"]["unknown"] + extra_unknown
        vals = []
        for r in chosen:
            entry, raw, side = float(r["entry_fill"]), float(r["exit_raw"]), int(float(r["side"]))
            exit_ = raw * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r["funding"]))
        n, wins = len(vals), sum(v > 0 for v in vals)
        assert row["known_trades"] == n and row["net_wins"] == wins
        assert close(row["mean_net_pct_notional"], 100 * math.fsum(vals) / n if n else None)
        positive, negative = math.fsum(v for v in vals if v > 0), -math.fsum(v for v in vals if v < 0)
        assert close(row["profit_factor"], positive / negative if negative else None)
        assert row["postclose_big_captured"] == sum(r["post_close_big"] == "True" for r in chosen)
        checked += n
    out = {"all_checks_pass": True, "groups_checked": len(result["rows"]), "repeated_scenario_paths_checked": checked, "input_ledger_rows_checked": len(ledger), "oi_points_checked": len(points), "post_close_bar_labels_checked": len(labels), "result_sha256": sha(result_file), "audit_code_sha256": sha(Path(__file__)), "note": "Independent accounting and time checks of previously audited historical sources, not a live or account test."}
    (H / "2024持仓量门独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS69_2024_AUDIT", json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
