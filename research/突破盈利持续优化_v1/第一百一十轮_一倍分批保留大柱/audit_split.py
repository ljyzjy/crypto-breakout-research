"""Independent partial-exit source joins and cost-accounting reconstruction."""
from datetime import datetime, timezone
from decimal import Decimal as D
import csv
import json
from pathlib import Path

import pandas as pd

from freeze_inputs import H, R98, R108, R70, R62, R102, sha


def near(a, b):
    return a is b if a is None or b is None else abs(D(str(a)) - D(str(b))) < D("1e-10")


def net(entry, raw, side, funding, slip):
    entry, raw, side, funding = D(str(entry)), D(str(raw)), D(int(side)), D(str(funding))
    exit_ = raw * (1 - side * slip)
    return side * (exit_ / entry - 1) - D(".0005") * (1 + exit_ / entry) - funding


def main():
    result_path = H / "分批退出单位结果.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["detail_sha256"] == sha(H / "分批退出逐笔.csv") and result["frozen_sha256"] == sha(H / "输入冻结.json")
    assert result["code_sha256"] == sha(H / "run_split.py")
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert frozen["code_sha256"] == sha(H / "freeze_inputs.py")
    for path, digest in frozen["files"].items():
        assert sha(Path(path)) == digest
    with (H / "分批退出逐笔.csv").open(encoding="utf-8", newline="") as f:
        detail = list(csv.DictReader(f))
    assert len(detail) == len({(r["year"], r["leverage"], r["observation_id"]) for r in detail})
    labels = pd.read_parquet(R102 / "事后大柱标签.parquet").set_index("observation_id").to_dict("index")
    original22 = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").to_dict("records")
    alt22 = pd.read_parquet(R108 / "一倍止盈单位账本.parquet").to_dict("records")
    orig22 = {(r["observation_id"], r["variant"]): r for r in original22}
    one22 = {(r["observation_id"], r["variant"]): r for r in alt22}
    paired22 = pd.read_csv(R108 / "一倍动态配对明细.csv")
    checked = 0
    for year in ("2022", "2024", "2026"):
        if year != "2022":
            snap = R62 / f"{year}完整批次_冻结"
            baseline = pd.read_parquet(snap / "batch/动态池单位收益与风险.parquet").to_dict("records")
            alternatives = json.loads((R70 / f"{year}一倍止盈本地风险账本.json").read_text(encoding="utf-8"))["records"]
            altmap = {(r["observation_id"], r["variant"]): r for r in alternatives}
            source_summary = json.loads((snap / f"support/{year}一秒观察对照.json").read_text(encoding="utf-8"))
        for lev in (10, 20):
            rows = [r for r in detail if r["year"] == year and int(r["leverage"]) == lev]
            variant = f"one_observation_2r_{lev}x"
            if year == "2022":
                ids = set(paired22.loc[paired22.leverage.eq(lev), "observation_id"])
                old = {obs: orig22[(obs, variant)] for obs in ids}
                new = {obs: one22[(obs, variant)] for obs in ids}
                unknown = 2
            else:
                old = {r["observation_id"]: r for r in baseline if r["variant"] == variant and r["status"] == r["risk_status"] == "verified" and not bool(r["liq_proxy"])}
                new = {obs: altmap.get((obs, f"one_observation_1r_{lev}x")) for obs in old}
                unknown = next(x for x in source_summary["rows"] if x["leverage"] == lev)["one_second_observation"]["unknown"]
            ok = {obs for obs, p in new.items() if p and p["status"] == p["risk_status"] == "verified" and not bool(p["liq_proxy"])}
            unknown += len(old) - len(ok)
            assert {r["observation_id"] for r in rows} == ok
            buckets = {(k, s): [] for k in ("two_r", "one_r", "half_split") for s in ("0.05", "0.075", "0.1")}
            labels_group = {k: [] for k in ("large_aligned", "other", "unknown")}
            days = set()
            for d in rows:
                obs, two, one = d["observation_id"], old[d["observation_id"]], new[d["observation_id"]]
                assert int(two["entry_ts"]) == int(one["entry_ts"]) == int(d["entry_ts"])
                assert int(two["side"]) == int(one["side"]) == int(d["side"])
                assert near(two["entry_fill"], one["entry_fill"]) and near(d["entry_fill"], two["entry_fill"])
                assert int(d["one_exit_ts"]) == int(one["exit_ts"]) and int(d["two_exit_ts"]) == int(two["exit_ts"])
                assert near(d["one_exit_raw"], one["exit_raw"]) and near(d["two_exit_raw"], two["exit_raw"])
                assert near(d["one_funding"], one["funding"]) and near(d["two_funding"], two["funding"])
                if year == "2022":
                    z = labels[obs]
                    label = "unknown" if z["status"] != "verified" else "large_aligned" if bool(z["large_aligned"]) else "other"
                    assert d["label"] == label
                else:
                    label = "not_evaluated"
                    assert d["label"] == label
                for slip_s in ("0.05", "0.075", "0.1"):
                    slip = D(slip_s) / 100
                    x = net(two["entry_fill"], two["exit_raw"], two["side"], two["funding"], slip)
                    y = net(one["entry_fill"], one["exit_raw"], one["side"], one["funding"], slip)
                    z = (x + y) / 2
                    buckets[("two_r", slip_s)].append(x)
                    buckets[("one_r", slip_s)].append(y)
                    buckets[("half_split", slip_s)].append(z)
                    if slip_s == "0.05":
                        assert near(d["two_net"], x) and near(d["one_net"], y) and near(d["split_net"], z)
                        if year == "2022":
                            labels_group[label].append((y, x, z))
                days.add(datetime.fromtimestamp(int(d["entry_ts"]) / 1000, timezone.utc).date())
                checked += 1
            for row in [x for x in result["rows"] if x["year"] == year and x["leverage"] == lev]:
                vals = buckets[(row["cohort"], str(row["exit_slippage_pct"]))]
                wins, losses = [v for v in vals if v > 0], [v for v in vals if v < 0]
                assert row["trades"] == len(vals) and row["wins"] == len(wins) and row["active_utc_days"] == len(days)
                assert row["unknown_candidates"] == unknown and row["additional_unpaired_unknown"] == len(old) - len(ok)
                assert near(row["win_rate_pct"], 100 * len(wins) / len(vals) if vals else None)
                assert near(row["mean_net_pct_notional"], D(100) * sum(vals, D(0)) / len(vals) if vals else None)
                assert near(row["profit_factor"], sum(wins, D(0)) / -sum(losses, D(0)) if losses else None)
            if year == "2022":
                for label, group in labels_group.items():
                    row = next(x for x in result["ex_post_2022_labels"] if x["leverage"] == lev and x["label"] == label)
                    assert row["trades"] == len(group)
                    for j, key in enumerate(("one_mean_pct", "two_mean_pct", "split_mean_pct")):
                        assert near(row[key], D(100) * sum((x[j] for x in group), D(0)) / len(group) if group else None)
    out = {"all_checks_pass": True, "paired_paths_checked": checked, "summary_groups_checked": len(result["rows"]),
           "result_sha256": sha(result_path), "detail_sha256": sha(H / "分批退出逐笔.csv"),
           "audit_code_sha256": sha(Path(__file__)),
           "note": "Independent equal-leg fees, funding and known-path grouping; no real exchange partial fills or portfolio equity."}
    (H / "分批退出独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
