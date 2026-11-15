"""Rebuild 1R and signal-time adaptive metrics independently of their summarizer."""
from datetime import datetime, timezone
from decimal import Decimal as D
import json
import math
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R102 = P / "第一百零二轮_大柱持有损益核查"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk


def near(a, b):
    return a is b if a is None or b is None else math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def main():
    bulk.runner.guard(start=True)
    result_path = H / "一倍动态结果汇总.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["code_sha256"] == bulk.sha(H / "summarize.py") and result["detail_sha256"] == bulk.sha(H / "一倍动态配对明细.csv")
    assert result["path_audit_sha256"] == bulk.sha(H / "一倍止盈逐笔独立核验.json")
    original = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    signals = pd.read_parquet(R98 / "原始逐笔批次/逐笔信号.parquet").set_index("observation_id").to_dict("index")
    labels = pd.read_parquet(R102 / "事后大柱标签.parquet").set_index("observation_id").to_dict("index")
    current = pd.read_parquet(H / "一倍止盈单位账本.parquet").to_dict("records")
    details = pd.read_csv(H / "一倍动态配对明细.csv")
    reference = json.loads((R98 / "原始逐笔汇总.json").read_text(encoding="utf-8"))
    checked = 0
    for lev in (10, 20):
        variant = f"one_observation_2r_{lev}x"
        subset = [r for r in current if r["variant"] == variant]
        pairs = [r for r in subset if r["risk_status"] == "verified" and not pd.isna(r["liq_proxy"]) and not bool(r["liq_proxy"])
                 and not pd.isna(signals[r["observation_id"]].get("one_imbalance"))]
        saved = details[details.leverage == lev].set_index("observation_id").to_dict("index")
        assert set(saved) == {r["observation_id"] for r in pairs}
        buckets = {(cohort, slip): [] for cohort in ("baseline_paired", "one_r", "adaptive") for slip in ("0.05", "0.075", "0.1")}
        by_label = {name: [] for name in ("large_aligned", "other", "unknown")}
        days = set()
        for alt in pairs:
            obs, sig = alt["observation_id"], signals[alt["observation_id"]]
            orig, label = original[(obs, variant)], labels[obs]
            flow = D(str(sig["one_imbalance"]))
            assert sig["status"] == "qualified" and sig[f"precheck_{lev}x"] == "passed" and flow >= D(".1")
            assert int(sig["entry_exec_ts"]) == int(orig["entry_signal_reference_ts"])
            adaptive, target = (orig, "2r") if flow >= D(".5") else (alt, "1r")
            label_name = "unknown" if label["status"] != "verified" else "large_aligned" if bool(label["large_aligned"]) else "other"
            item = saved[obs]
            assert item["adaptive_target"] == target and item["label"] == label_name and item["one_r_action"] == alt["one_r_action"]
            for col, rec in (("baseline_net", orig), ("one_r_net", alt), ("adaptive_net", adaptive)):
                assert near(item[col], rec["net_per_unit_notional"])
            days.add(datetime.fromtimestamp(int(alt["entry_ts"]) / 1000, timezone.utc).date())
            by_label[label_name].append((orig, alt, adaptive))
            for cohort, rec in (("baseline_paired", orig), ("one_r", alt), ("adaptive", adaptive)):
                side, entry, raw, fund = D(int(rec["side"])), D(str(rec["entry_fill"])), D(str(rec["exit_raw"])), D(str(rec["funding"]))
                for slip in ("0.05", "0.075", "0.1"):
                    exit_ = raw * (1 - side * D(slip) / 100)
                    net = side * (exit_ / entry - 1) - D(".0005") * (1 + exit_ / entry) - fund
                    buckets[(cohort, slip)].append(net)
            checked += 1
        baseline = next(r for r in reference["rows"] if r["leverage"] == lev and r["exit_slippage_pct"] == .05)
        for row in [r for r in result["rows"] if r["leverage"] == lev and not r["cohort"].startswith("label_")]:
            vals = buckets[(row["cohort"], str(row["exit_slippage_pct"]))]
            wins, losses = [x for x in vals if x > 0], [x for x in vals if x < 0]
            assert row["trades"] == len(pairs) == len(vals) and row["net_wins"] == len(wins)
            assert row["active_utc_days"] == len(days) and row["known_no_order"] == baseline["known_no_order"]
            assert row["extra_unknown_paths"] == len(subset) - len(pairs)
            assert row["unknown_candidates"] == baseline["unknown_candidates"] + len(subset) - len(pairs)
            assert near(row["net_win_rate_pct"], 100 * len(wins) / len(vals) if vals else None)
            assert near(row["mean_net_pct_notional"], 100 * sum(vals) / len(vals) if vals else None)
            assert near(row["profit_factor"], sum(wins) / -sum(losses) if losses else None)
        for name, group in by_label.items():
            row = next(r for r in result["rows"] if r["leverage"] == lev and r["cohort"] == "label_" + name)
            assert row["paths"] == len(group) and row["one_r_earlier"] == sum(g[1]["one_r_action"] == "one_r_exit" for g in group)
            for i, field in enumerate(("baseline_mean_pct", "one_r_mean_pct", "adaptive_mean_pct")):
                assert near(row[field], 100 * sum(float(g[i]["net_per_unit_notional"]) for g in group) / len(group) if group else None)
    out = {"all_checks_pass": True, "paired_paths_checked": checked, "summary_groups_checked": len(result["rows"]),
           "result_sha256": bulk.sha(result_path), "detail_sha256": bulk.sha(H / "一倍动态配对明细.csv"),
           "code_sha256": bulk.sha(Path(__file__)), "note": "Signal-time exit choice and paired unit costs checked; labels remain ex-post."}
    (H / "一倍动态汇总独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT108_SUMMARY_AUDIT", checked, flush=True)


if __name__ == "__main__":
    main()
