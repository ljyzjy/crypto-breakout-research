"""Matched 1R/2R half-notional exits across previously audited entry paths."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path

import pandas as pd

from split_math import half_and_half, leg_net
from freeze_inputs import H, R98, R108, R70, R62, R102, sha


def complete(row):
    return bool(row and row.get("status") == "verified" and row.get("risk_status") == "verified"
                and not pd.isna(row.get("liq_proxy")) and not bool(row["liq_proxy"]))


def main():
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert frozen["code_sha256"] == sha(H / "freeze_inputs.py")
    for path, digest in frozen["files"].items():
        assert sha(Path(path)) == digest
    labels = pd.read_parquet(R102 / "事后大柱标签.parquet").set_index("observation_id").to_dict("index")
    original22 = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").to_dict("records")
    alt22 = pd.read_parquet(R108 / "一倍止盈单位账本.parquet").to_dict("records")
    pairs22 = pd.read_csv(R108 / "一倍动态配对明细.csv")
    origmap22 = {(r["observation_id"], r["variant"]): r for r in original22}
    altmap22 = {(r["observation_id"], r["variant"]): r for r in alt22}
    detail, metrics = [], []
    for year in ("2022", "2024", "2026"):
        if year != "2022":
            snap = R62 / f"{year}完整批次_冻结"
            original = pd.read_parquet(snap / "batch/动态池单位收益与风险.parquet").to_dict("records")
            risk = json.loads((R70 / f"{year}一倍止盈本地风险账本.json").read_text(encoding="utf-8"))
            altmap = {(r["observation_id"], r["variant"]): r for r in risk["records"]}
            baseline = json.loads((snap / f"support/{year}一秒观察对照.json").read_text(encoding="utf-8"))
        else:
            original, altmap, baseline = original22, altmap22, None
        for lev in (10, 20):
            variant = f"one_observation_2r_{lev}x"
            if year == "2022":
                ids = set(pairs22.loc[pairs22.leverage.eq(lev), "observation_id"])
                old = {obs: origmap22[(obs, variant)] for obs in ids}
                new = {obs: altmap22[(obs, variant)] for obs in ids}
                unknown = 2
            else:
                old = {r["observation_id"]: r for r in original if r["variant"] == variant and complete(r)}
                new = {obs: altmap.get((obs, f"one_observation_1r_{lev}x")) for obs in old}
                ref = next(r for r in baseline["rows"] if r["leverage"] == lev)
                assert len(old) == ref["one_second_observation"]["trades"]
                unknown = ref["one_second_observation"]["unknown"]
            missing = sum(not complete(x) for x in new.values())
            unknown += missing
            matched = [(obs, old[obs], new[obs]) for obs in sorted(old) if complete(old[obs]) and complete(new[obs])]
            assert len(matched) + missing == len(old)
            values = {(kind, slip): [] for kind in ("two_r", "one_r", "half_split")
                      for slip in (D(".0005"), D(".00075"), D(".001"))}
            for obs, two, one in matched:
                assert int(one["entry_ts"]) == int(two["entry_ts"]) and int(one["side"]) == int(two["side"])
                assert abs(D(str(one["entry_fill"])) - D(str(two["entry_fill"]))) < D("1e-9")
                assert abs(D(str(one["initial_stop"])) - D(str(two["initial_stop"]))) < D("1e-9")
                for r in (one, two):
                    assert int(r["exit_ts"]) >= int(r["exit_signal_ts"]) + 5000
                    assert abs(leg_net(r, D(".0005")) - D(str(r["net_per_unit_notional"]))) < D("1e-11")
                for slip in (D(".0005"), D(".00075"), D(".001")):
                    values[("one_r", slip)].append(leg_net(one, slip))
                    values[("two_r", slip)].append(leg_net(two, slip))
                    values[("half_split", slip)].append(half_and_half(one, two, slip))
                label = "not_evaluated"
                if year == "2022":
                    z = labels[obs]
                    label = "unknown" if z["status"] != "verified" else "large_aligned" if bool(z["large_aligned"]) else "other"
                detail.append({"year": year, "leverage": lev, "observation_id": obs, "entry_ts": int(two["entry_ts"]),
                               "side": int(two["side"]), "entry_fill": str(two["entry_fill"]),
                               "one_exit_ts": int(one["exit_ts"]), "one_exit_raw": str(one["exit_raw"]), "one_funding": str(one["funding"]),
                               "two_exit_ts": int(two["exit_ts"]), "two_exit_raw": str(two["exit_raw"]), "two_funding": str(two["funding"]),
                               "two_net": str(leg_net(two, D(".0005"))), "one_net": str(leg_net(one, D(".0005"))),
                               "split_net": str(half_and_half(one, two, D(".0005"))), "label": label})
            days = {datetime.fromtimestamp(int(two["entry_ts"]) / 1000, timezone.utc).date().isoformat() for _, two, _ in matched}
            for (kind, slip), vals in values.items():
                pos = sum((x for x in vals if x > 0), D(0))
                neg = -sum((x for x in vals if x < 0), D(0))
                metrics.append({"year": year, "leverage": lev, "cohort": kind, "exit_slippage_pct": float(slip * 100),
                                "trades": len(vals), "wins": sum(x > 0 for x in vals),
                                "win_rate_pct": float(D(100) * sum(x > 0 for x in vals) / len(vals)) if vals else None,
                                "mean_net_pct_notional": float(D(100) * sum(vals, D(0)) / len(vals)) if vals else None,
                                "profit_factor": float(pos / neg) if neg else None, "active_utc_days": len(days),
                                "unknown_candidates": int(unknown), "additional_unpaired_unknown": missing})
    with (H / "分批退出逐笔.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0]))
        w.writeheader()
        w.writerows(detail)
    label_rows = []
    for lev in (10, 20):
        for label in ("large_aligned", "other", "unknown"):
            rows = [r for r in detail if r["year"] == "2022" and r["leverage"] == lev and r["label"] == label]
            label_rows.append({"leverage": lev, "label": label, "trades": len(rows),
                               **{name + "_mean_pct": float(D(100) * sum((D(r[name + "_net"]) for r in rows), D(0)) / len(rows)) if rows else None
                                  for name in ("one", "two", "split")}})
    output = {"rows": metrics, "ex_post_2022_labels": label_rows, "detail_sha256": sha(H / "分批退出逐笔.csv"),
              "frozen_sha256": sha(H / "输入冻结.json"), "code_sha256": sha(Path(__file__)),
              "note": "Known equal-notional historical paths; no shared-wallet release, actual fills, or independent future sample."}
    (H / "分批退出单位结果.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for x in metrics:
        if x["leverage"] == 20 and x["exit_slippage_pct"] == .05:
            print("EXT110_UNIT", json.dumps(x, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
