"""Paired original, 1R and trailing outcomes after independent path audit."""
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R102 = P / "第一百零二轮_大柱持有损益核查"
R108 = P / "第一百零八轮_原始逐笔一倍与动态止盈"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk


def metrics(paths, slip):
    values = []
    for p in paths:
        side, entry, raw, funding = D(int(p["side"])), D(str(p["entry_fill"])), D(str(p["exit_raw"])), D(str(p["funding"]))
        exit_ = raw * (1 - side * slip)
        values.append(side * (exit_ - entry) / entry - D(".0005") * (1 + exit_ / entry) - funding)
    wins = sum(x > 0 for x in values)
    positive = sum((x for x in values if x > 0), D(0))
    negative = -sum((x for x in values if x < 0), D(0))
    days = len({datetime.fromtimestamp(int(x["entry_ts"]) / 1000, timezone.utc).date() for x in paths})
    return {"trades": len(values), "wins": wins, "win_rate_pct": float(D(100) * wins / len(values)) if values else None,
            "mean_net_pct_notional": float(D(100) * sum(values, D(0)) / len(values)) if values else None,
            "profit_factor": float(positive / negative) if negative else None, "active_utc_days": days}


def main():
    bulk.runner.guard(start=True)
    audit = json.loads((H / "跟踪退出逐笔独立核验.json").read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["paths_checked"] == 261
    assert audit["ledger_sha256"] == bulk.sha(H / "跟踪退出单位账本.parquet")
    assert audit["code_sha256"] == bulk.sha(H / "audit_trailing.py") and audit["logic_sha256"] == bulk.sha(H / "audit_trailing_logic.py")
    label_audit = json.loads((R102 / "大柱标签独立核验.json").read_text(encoding="utf-8"))
    assert label_audit["all_checks_pass"] and label_audit["labels_sha256"] == bulk.sha(R102 / "事后大柱标签.parquet")
    labels = pd.read_parquet(R102 / "事后大柱标签.parquet").set_index("observation_id").to_dict("index")
    original = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    one = pd.read_parquet(R108 / "一倍止盈单位账本.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    trailing = pd.read_parquet(H / "跟踪退出单位账本.parquet").to_dict("records")
    reference = json.loads((R98 / "原始逐笔汇总.json").read_text(encoding="utf-8"))
    results, details = [], []
    for lev in (10, 20):
        variant = f"one_observation_2r_{lev}x"
        subset = [x for x in trailing if x["variant"] == variant]
        pairs = []
        for path in subset:
            key = (path["observation_id"], variant)
            one_path, baseline = one[key], original[key]
            if any(x["risk_status"] != "verified" or pd.isna(x["liq_proxy"]) or bool(x["liq_proxy"]) for x in (path, one_path, baseline)):
                continue
            assert all(int(x["entry_ts"]) == int(path["entry_ts"]) for x in (one_path, baseline))
            assert all(abs(D(str(x["entry_fill"])) - D(str(path["entry_fill"]))) < D("1e-9") for x in (one_path, baseline))
            lbl = labels[path["observation_id"]]
            label = "unknown" if lbl["status"] != "verified" else "large_aligned" if bool(lbl["large_aligned"]) else "other"
            pairs.append((baseline, one_path, path, label))
            details.append({"observation_id": path["observation_id"], "leverage": lev, "entry_ts": int(path["entry_ts"]),
                            "label": label, "trailing_action": path["trailing_action"],
                            "original_net": str(baseline["net_per_unit_notional"]), "one_r_net": str(one_path["net_per_unit_notional"]),
                            "trailing_net": str(path["net_per_unit_notional"])})
        ref = next(x for x in reference["rows"] if x["leverage"] == lev and x["exit_slippage_pct"] == .05)
        extra_unknown = len(subset) - len(pairs)
        for idx, rule in ((0, "original_2r"), (1, "one_r"), (2, "trailing")):
            for slip in (D(".0005"), D(".00075"), D(".001")):
                results.append({"leverage": lev, "rule": rule, "exit_slippage_pct": float(100 * slip),
                                **metrics([x[idx] for x in pairs], slip), "original_unknown": ref["unknown_candidates"],
                                "additional_pair_unknown": extra_unknown})
        for label in ("large_aligned", "other", "unknown"):
            selected = [p for p in pairs if p[3] == label]
            results.append({"leverage": lev, "rule": "label_" + label, "paths": len(selected),
                            "trailing_earlier": sum(p[2]["trailing_action"] == "trailing_exit" for p in selected),
                            "original_mean_net_pct": metrics([p[0] for p in selected], D(".0005"))["mean_net_pct_notional"],
                            "one_r_mean_net_pct": metrics([p[1] for p in selected], D(".0005"))["mean_net_pct_notional"],
                            "trailing_mean_net_pct": metrics([p[2] for p in selected], D(".0005"))["mean_net_pct_notional"]})
    detail_path = H / "跟踪退出配对明细.csv"
    pd.DataFrame(details).to_csv(detail_path, index=False, encoding="utf-8")
    out = {"rows": results, "detail_sha256": bulk.sha(detail_path), "audit_sha256": bulk.sha(H / "跟踪退出逐笔独立核验.json"),
           "code_sha256": bulk.sha(Path(__file__)), "note": "Equal-notional historical paths, not an account or real fills."}
    (H / "跟踪退出配对结果.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT112_SUMMARY", json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
