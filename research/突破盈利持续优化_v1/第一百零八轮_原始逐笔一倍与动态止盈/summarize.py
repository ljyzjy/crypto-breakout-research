"""Pair original, 1R and causal flow-selected exits after full replay audit."""
from decimal import Decimal as D
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R102 = P / "第一百零二轮_大柱持有损益核查"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
from summarize import metric


def main():
    bulk.runner.guard(start=True)
    audit = json.loads((H / "一倍止盈逐笔独立核验.json").read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["paths_checked"] == 261
    assert audit["ledger_sha256"] == bulk.sha(H / "一倍止盈单位账本.parquet")
    assert audit["code_sha256"] == bulk.sha(H / "audit_exit.py")
    label_audit = json.loads((R102 / "大柱标签独立核验.json").read_text(encoding="utf-8"))
    assert label_audit["all_checks_pass"] and label_audit["labels_sha256"] == bulk.sha(R102 / "事后大柱标签.parquet")
    labels = pd.read_parquet(R102 / "事后大柱标签.parquet").set_index("observation_id").to_dict("index")
    original = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    signals = pd.read_parquet(R98 / "原始逐笔批次/逐笔信号.parquet").set_index("observation_id").to_dict("index")
    current = pd.read_parquet(H / "一倍止盈单位账本.parquet").to_dict("records")
    reference = json.loads((R98 / "原始逐笔汇总.json").read_text(encoding="utf-8"))
    output, details = [], []
    for lev in (10, 20):
        variant = f"one_observation_2r_{lev}x"
        subset = [r for r in current if r["variant"] == variant]
        paired = []
        for r in subset:
            s = signals[r["observation_id"]]
            if r["risk_status"] != "verified" or pd.isna(r["liq_proxy"]) or bool(r["liq_proxy"]) or pd.isna(s.get("one_imbalance")):
                continue
            assert s["status"] == "qualified" and s[f"precheck_{lev}x"] == "passed"
            orig = original[(r["observation_id"], variant)]
            assert int(s["entry_exec_ts"]) == int(orig["entry_signal_reference_ts"])
            flow = D(str(s["one_imbalance"]))
            assert flow >= D(".1")
            adaptive = orig if flow >= D(".5") else r
            label = labels[r["observation_id"]]
            assert int(label["side"]) == int(r["side"])
            name = "unknown" if label["status"] != "verified" else "large_aligned" if bool(label["large_aligned"]) else "other"
            details.append({"observation_id": r["observation_id"], "leverage": lev, "entry_ts": int(r["entry_ts"]),
                            "one_imbalance": str(flow), "label": name, "one_r_action": r["one_r_action"],
                            "adaptive_target": "2r" if flow >= D(".5") else "1r",
                            "baseline_net": str(orig["net_per_unit_notional"]), "one_r_net": str(r["net_per_unit_notional"]),
                            "adaptive_net": str(adaptive["net_per_unit_notional"])})
            paired.append((orig, r, adaptive))
        original_summary = next(x for x in reference["rows"] if x["leverage"] == lev and x["exit_slippage_pct"] == .05)
        unknown = int(original_summary["unknown_candidates"]) + len(subset) - len(paired)
        for index, name in ((0, "baseline_paired"), (1, "one_r"), (2, "adaptive")):
            paths = []
            for group in paired:
                x = group[index]
                paths.append({"entry_ts": int(x["entry_ts"]), "side": str(int(x["side"])),
                              "entry_fill": str(x["entry_fill"]), "exit_raw": str(x["exit_raw"]), "funding": str(x["funding"])})
            for slip in (D(".0005"), D(".00075"), D(".001")):
                output.append({"leverage": lev, "cohort": name, "exit_slippage_pct": float(100 * slip), **metric(paths, slip),
                               "known_no_order": original_summary["known_no_order"], "unknown_candidates": unknown,
                               "extra_unknown_paths": len(subset) - len(paired)})
        for name in ("large_aligned", "other", "unknown"):
            group = [d for d in details if d["leverage"] == lev and d["label"] == name]
            output.append({"leverage": lev, "cohort": "label_" + name, "paths": len(group),
                           "one_r_earlier": sum(d["one_r_action"] == "one_r_exit" for d in group),
                           "baseline_mean_pct": float(D(100) * sum((D(d["baseline_net"]) for d in group), D(0)) / len(group)) if group else None,
                           "one_r_mean_pct": float(D(100) * sum((D(d["one_r_net"]) for d in group), D(0)) / len(group)) if group else None,
                           "adaptive_mean_pct": float(D(100) * sum((D(d["adaptive_net"]) for d in group), D(0)) / len(group)) if group else None})
    detail_path = H / "一倍动态配对明细.csv"
    pd.DataFrame(details).to_csv(detail_path, index=False, encoding="utf-8")
    result = {"rows": output, "detail_sha256": bulk.sha(detail_path), "path_audit_sha256": bulk.sha(H / "一倍止盈逐笔独立核验.json"),
              "label_audit_sha256": bulk.sha(R102 / "大柱标签独立核验.json"), "code_sha256": bulk.sha(Path(__file__)),
              "note": "Paired known paths, historical exploration, ex-post labels are not entry signals; no account or real fills."}
    (H / "一倍动态结果汇总.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT108_SUMMARY", json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
