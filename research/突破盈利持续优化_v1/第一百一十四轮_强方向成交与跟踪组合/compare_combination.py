"""Fixed first-second direction gate with original and trailing exits."""
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R62 = P / "第六十二轮_一秒观察更早突破"
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R112 = P / "第一百一十二轮_突破后跟踪退出"
R113 = P / "第一百一十三轮_跟踪退出跨期验证"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk


def metric(rows, rule, slip):
    values = []
    for r in rows:
        side, entry = D(int(r["side"])), D(r["entry_fill"])
        raw, funding = D(r[rule + "_exit_raw"]), D(r[rule + "_funding"])
        exit_ = raw * (1 - side * slip)
        values.append(side * (exit_ - entry) / entry - D(".0005") * (1 + exit_ / entry) - funding)
    profit = sum((v for v in values if v > 0), D(0))
    loss = -sum((v for v in values if v < 0), D(0))
    return {"trades": len(values), "wins": sum(v > 0 for v in values),
            "win_rate_pct": float(D(100) * sum(v > 0 for v in values) / len(values)) if values else None,
            "mean_net_pct_notional": float(D(100) * sum(values, D(0)) / len(values)) if values else None,
            "profit_factor": float(profit / loss) if loss else None,
            "active_utc_days": len({datetime.fromtimestamp(int(x["entry_ts"]) / 1000, timezone.utc).date() for x in rows})}


def main():
    bulk.runner.guard(start=True)
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert frozen["code_sha256"] == bulk.sha(H / "freeze_inputs.py") and frozen["threshold"] == "0.50"
    for path, digest in frozen["sources"].items():
        assert bulk.sha(path) == digest
    all_cases = []
    for year in ("2022", "2024", "2026"):
        if year == "2022":
            signals = pd.read_parquet(R98 / "原始逐笔批次/逐笔信号.parquet").set_index("observation_id")
            base = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet")
            alt = pd.read_parquet(R112 / "跟踪退出单位账本.parquet")
            detail = pd.read_csv(R112 / "跟踪退出配对明细.csv")
        else:
            snap = R62 / f"{year}完整批次_冻结"
            signals = pd.read_parquet(snap / "batch/动态池逐笔信号筛查.parquet").set_index("observation_id")
            base = pd.read_parquet(snap / "batch/动态池单位收益与风险.parquet")
            alt = pd.DataFrame(json.loads((R113 / f"{year}跟踪退出风险账本.json").read_text(encoding="utf-8"))["records"])
            cross = pd.read_csv(R113 / "跨期跟踪退出配对明细.csv", dtype={"year": str})
            detail = cross[cross.year == year]
        assert signals.index.is_unique and not detail.duplicated(["observation_id", "leverage"]).any()
        orig = base.set_index(["observation_id", "variant"]).to_dict("index")
        trail = alt.set_index(["observation_id", "variant"]).to_dict("index")
        for x in detail.to_dict("records"):
            obs, lev = x["observation_id"], int(x["leverage"])
            variant = f"one_observation_2r_{lev}x"
            a, b, sig = orig[(obs, variant)], trail[(obs, variant)], signals.loc[obs].to_dict()
            assert sig["status"] == "qualified" and sig[f"precheck_{lev}x"] == "passed"
            assert a["risk_status"] == b["risk_status"] == "verified" and not bool(a["liq_proxy"]) and not bool(b["liq_proxy"])
            assert int(a["entry_ts"]) == int(b["entry_ts"]) and abs(D(str(a["entry_fill"])) - D(str(b["entry_fill"]))) < D("1e-9")
            assert int(sig["entry_exec_ts"]) >= int(sig["decision_ts"]) + 1000
            assert int(a["entry_signal_reference_ts"]) == int(sig["entry_exec_ts"]) and int(a["entry_ts"]) >= int(sig["entry_exec_ts"]) + 1000
            missing = pd.isna(sig["one_imbalance"]) or pd.isna(sig["buy_notional"]) or pd.isna(sig["sell_notional"])
            if missing:
                gate, imbalance = "unknown", None
            else:
                buy, sell = D(str(sig["buy_notional"])), D(str(sig["sell_notional"]))
                assert buy + sell > 0 and int(sig["one_count"]) >= 3
                derived = D(int(sig["side"])) * (buy - sell) / (buy + sell)
                imbalance = D(str(sig["one_imbalance"]))
                assert abs(derived - imbalance) < D("1e-9") and D(int(sig["side"])) == D(int(a["side"]))
                gate = "pass" if imbalance >= D(".50") else "reject"
            all_cases.append({"year": year, "leverage": lev, "observation_id": obs, "gate": gate,
                              "imbalance": str(imbalance) if imbalance is not None else None,
                              "side": int(a["side"]), "decision_ts": int(sig["decision_ts"]), "reference_ts": int(sig["entry_exec_ts"]),
                              "entry_ts": int(a["entry_ts"]), "entry_fill": str(a["entry_fill"]),
                              "original_exit_raw": str(a["exit_raw"]), "original_funding": str(a["funding"]),
                              "trailing_exit_raw": str(b["exit_raw"]), "trailing_funding": str(b["funding"])})
    assert len(all_cases) == 359
    output = []
    for year in ("2022", "2024", "2026"):
        for lev in (10, 20):
            group = [x for x in all_cases if x["year"] == year and x["leverage"] == lev]
            for filtering in (False, True):
                cohort = [x for x in group if not filtering or x["gate"] == "pass"]
                for rule in ("original", "trailing"):
                    for slip in (D(".0005"), D(".00075"), D(".001")):
                        output.append({"year": year, "leverage": lev, "gate": "strong" if filtering else "all",
                                       "exit": rule, "exit_slippage_pct": float(100 * slip), **metric(cohort, rule, slip),
                                       "original_unknown_candidates": {"2022": 2, "2024": 16, "2026": 4}[year],
                                       "additional_gate_unknown": sum(x["gate"] == "unknown" for x in group) if filtering else 0,
                                       "rejected_by_gate": sum(x["gate"] == "reject" for x in group) if filtering else 0})
    detail_path = H / "强方向组合逐笔.csv"
    pd.DataFrame(all_cases).to_csv(detail_path, index=False, encoding="utf-8")
    result = {"rows": output, "detail_sha256": bulk.sha(detail_path), "frozen_sha256": bulk.sha(H / "输入冻结.json"),
              "code_sha256": bulk.sha(Path(__file__)), "note": "Fixed historical known paths; ex-post labels never used for entry."}
    (H / "强方向组合结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT114_COMBINED", json.dumps([x for x in output if x["leverage"] == 20 and x["exit_slippage_pct"] == .05], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
