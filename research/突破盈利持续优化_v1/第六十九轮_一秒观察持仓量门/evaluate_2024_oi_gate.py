"""Apply the fixed OI gate to the fully audited 2024 one-second paths."""
from collections import Counter
from decimal import Decimal, getcontext
from pathlib import Path
import csv
import json

from evaluate_2026_oi_gate import metrics, sha

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent
SNAP = P / "第六十二轮_一秒观察更早突破/2024完整批次_冻结"
BIG = P / "第五十八轮_BTCETH持仓量状态/大柱捕捉事后明细.csv"


def main():
    audit_file = H / "2024持仓量逐点核验.json"
    audit = json.loads(audit_file.read_text(encoding="utf-8"))
    assert audit["plan_sha256"] == sha(H / "冻结研究方案.md") and audit["code_sha256"] == sha(H / "prepare_2024_oi_points.py")
    csv_path = H / "2024一秒观察已核验账本.csv"
    assert audit["ledger_csv_sha256"] == sha(csv_path)
    snapshot = json.loads((SNAP / "完整快照哈希.json").read_text(encoding="utf-8"))
    assert snapshot["all_checks_pass"] and audit["snapshot_manifest_sha256"] == sha(SNAP / "完整快照哈希.json")
    point_map = {(p["symbol"], int(p["ts"])): p for p in audit["points"]}
    assert len(point_map) == len(audit["points"])
    events = {x["observation_id"]: x for x in audit["events"]}
    assert len(events) == len(audit["events"])
    with csv_path.open(encoding="utf-8", newline="") as f:
        ledger = list(csv.DictReader(f))
    assert ledger and len({(r["observation_id"], r["variant"]) for r in ledger}) == len(ledger)
    with BIG.open(encoding="utf-8-sig", newline="") as f:
        big_rows = list(csv.DictReader(f))
    known_big = {(r["contract"], int(r["quarter_start"]), int(r["allowed_side"])) for r in big_rows if r["year"] == "2024" and r["leverage"] == "20" and r["variant"] == "one_second"}
    assert len(known_big) == 22
    detail = []
    for row in ledger:
        obs = row["observation_id"]
        e = events[obs]
        assert int(float(row["decision_ts"])) == e["decision_ts"]
        values = {}
        status = "verified"
        for sym in ("BTCUSDT", "ETHUSDT"):
            x, y = point_map.get((sym, e["oi_t0"])), point_map.get((sym, e["oi_previous"]))
            if x is None or y is None or x["status"] != "verified" or y["status"] != "verified":
                status = "unknown_oi"
                continue
            current, old = D(str(x["values"][0])), D(str(y["values"][0]))
            if not current.is_finite() or not old.is_finite() or current <= 0 or old <= 0:
                status = "unknown_oi"
                continue
            values[sym] = current / old - 1
        gate = all(values[s] > 0 for s in ("BTCUSDT", "ETHUSDT")) if status == "verified" else None
        side = int(float(row["side"]))
        assert side in (-1, 1)
        entry, exit_raw = D(row["entry_fill"]), D(row["exit_raw"])
        assert abs(D(row["entry_fee"]) - D("0.0005")) < D("1e-12")
        base_exit = exit_raw * (1 - D(side) * D("0.0005"))
        net = D(side) * (base_exit - entry) / entry - D("0.0005") - D("0.0005") * base_exit / entry - D(row["funding"])
        assert abs(net - D(row["net_per_unit_notional"])) < D("1e-12")
        symbol = obs.split("|")[1]
        is_big = (symbol, (int(e["decision_ts"]) // 900000) * 900000, side) in known_big
        detail.append({"observation_id": obs, "variant": row["variant"], "decision_ts": e["decision_ts"], "oi_t0": e["oi_t0"], "oi_previous": e["oi_previous"], "oi_status": status, "gate": gate, "btc_change": float(values["BTCUSDT"]) if "BTCUSDT" in values else None, "eth_change": float(values["ETHUSDT"]) if "ETHUSDT" in values else None, "entry_ts": int(row["entry_ts"]), "entry_fill": entry, "exit_raw": exit_raw, "side": side, "funding": D(row["funding"]), "net": net, "post_close_big": is_big})
    previous = json.loads((SNAP / "support/2024一秒观察对照.json").read_text(encoding="utf-8"))
    results = []
    for lev in (10, 20):
        universe = [r for r in detail if r["variant"] == f"one_observation_2r_{lev}x"]
        baseline = next(x for x in previous["rows"] if x["leverage"] == lev)
        assert len(universe) == baseline["one_second_observation"]["trades"]
        extra_unknown = sum(r["gate"] is None for r in universe)
        for strategy in ("base", "oi_gate"):
            chosen = universe if strategy == "base" else [r for r in universe if r["gate"] is True]
            unknown = baseline["one_second_observation"]["unknown"] + (extra_unknown if strategy == "oi_gate" else 0)
            no_order = baseline["known_no_order"] + (sum(r["gate"] is False for r in universe) if strategy == "oi_gate" else 0)
            assert len(chosen) + unknown + no_order == baseline["candidate_events"] == 119
            for slip in (D("0.0005"), D("0.00075"), D("0.001")):
                records = []
                for r in chosen:
                    entry = r["entry_fill"]
                    exit_ = r["exit_raw"] * (1 - D(r["side"]) * slip)
                    net = D(r["side"]) * (exit_ - entry) / entry - D("0.0005") - D("0.0005") * exit_ / entry - r["funding"]
                    records.append({**r, "net": net})
                results.append({"leverage": lev, "strategy": strategy, "exit_slippage_pct": float(100 * slip), **metrics(records, unknown), "known_no_order": no_order, "postclose_big_captured": sum(r["post_close_big"] for r in chosen)})
        r = next(x for x in results if x["leverage"] == lev and x["strategy"] == "base" and x["exit_slippage_pct"] == 0.05)
        p = baseline["one_second_observation"]
        assert r["known_trades"] == p["trades"] and r["net_wins"] == p["wins"]
        if r["known_trades"]:
            assert abs(r["mean_net_pct_notional"] - p["mean_net_pct_notional"]) < 1e-10
    out = {"year": "2024", "rows": results, "gate_status_counts_20x": dict(Counter(r["oi_status"] for r in detail if r["variant"].endswith("20x"))), "big_candidate_bars": len(known_big), "original_unknown_candidates": 16, "inputs": {"point_audit_sha256": sha(audit_file), "ledger_csv_sha256": sha(csv_path), "postclose_bar_labels_sha256": sha(BIG), "plan_sha256": sha(H / "冻结研究方案.md")}, "note": "Historical exploration; post-close tags not used in entry; no shared account or live OI availability."}
    (H / "2024一秒观察持仓量对照.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    cols = ["observation_id", "variant", "decision_ts", "oi_t0", "oi_previous", "oi_status", "gate", "btc_change", "eth_change", "entry_ts", "entry_fill", "exit_raw", "side", "funding", "net", "post_close_big"]
    with (H / "2024一秒观察持仓量逐笔.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(detail)
    for r in results:
        if r["leverage"] == 20:
            print("OBS69_2024_RESULT", r, flush=True)


if __name__ == "__main__":
    main()
