"""Independently reconstruct gate decisions and unit-return group arithmetic."""
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


def main():
    bulk.runner.guard(start=True)
    result = json.loads((H / "强方向组合结果.json").read_text(encoding="utf-8"))
    assert result["code_sha256"] == bulk.sha(H / "compare_combination.py")
    assert result["detail_sha256"] == bulk.sha(H / "强方向组合逐笔.csv")
    assert result["frozen_sha256"] == bulk.sha(H / "输入冻结.json")
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    for path, sha in frozen["sources"].items():
        assert bulk.sha(path) == sha
    cases = pd.read_csv(H / "强方向组合逐笔.csv", dtype={"year": str})
    assert len(cases) == 359 and not cases.duplicated(["year", "leverage", "observation_id"]).any()
    checked = 0
    for year in ("2022", "2024", "2026"):
        if year == "2022":
            signals = pd.read_parquet(R98 / "原始逐笔批次/逐笔信号.parquet").set_index("observation_id")
            base = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet")
            alt = pd.read_parquet(R112 / "跟踪退出单位账本.parquet")
        else:
            snap = R62 / f"{year}完整批次_冻结"
            signals = pd.read_parquet(snap / "batch/动态池逐笔信号筛查.parquet").set_index("observation_id")
            base = pd.read_parquet(snap / "batch/动态池单位收益与风险.parquet")
            alt = pd.DataFrame(json.loads((R113 / f"{year}跟踪退出风险账本.json").read_text(encoding="utf-8"))["records"])
        original = base.set_index(["observation_id", "variant"]).to_dict("index")
        trailing = alt.set_index(["observation_id", "variant"]).to_dict("index")
        for c in cases[cases.year == year].to_dict("records"):
            obs, lev = c["observation_id"], int(c["leverage"])
            var = f"one_observation_2r_{lev}x"
            sig, a, b = signals.loc[obs], original[(obs, var)], trailing[(obs, var)]
            if pd.isna(sig["buy_notional"]) or pd.isna(sig["sell_notional"]) or pd.isna(sig["one_imbalance"]):
                gate = "unknown"
            else:
                buy, sell = D(str(sig["buy_notional"])), D(str(sig["sell_notional"]))
                signed = D(int(sig["side"])) * (buy - sell)
                gate = "pass" if D(2) * signed >= buy + sell else "reject"
                assert abs(D(str(c["imbalance"])) - signed / (buy + sell)) < D("1e-9")
            assert c["gate"] == gate
            assert int(c["decision_ts"]) + 1000 <= int(c["reference_ts"]) and int(c["reference_ts"]) + 1000 <= int(c["entry_ts"])
            assert int(c["reference_ts"]) == int(a["entry_signal_reference_ts"]) and int(c["entry_ts"]) == int(a["entry_ts"]) == int(b["entry_ts"])
            assert int(c["side"]) == int(a["side"]) == int(b["side"])
            for label, path in (("original", a), ("trailing", b)):
                assert abs(D(str(c[label + "_exit_raw"])) - D(str(path["exit_raw"]))) < D("1e-9")
                assert abs(D(str(c[label + "_funding"])) - D(str(path["funding"]))) < D("1e-10")
            checked += 1
    for item in result["rows"]:
        group = cases[(cases.year == item["year"]) & (cases.leverage == item["leverage"])]
        selected = group[group.gate == "pass"] if item["gate"] == "strong" else group
        assert len(selected) == item["trades"]
        if item["gate"] == "strong":
            assert int((group.gate == "reject").sum()) == item["rejected_by_gate"]
            assert int((group.gate == "unknown").sum()) == item["additional_gate_unknown"]
        slip = item["exit_slippage_pct"] / 100
        raw = selected[item["exit"] + "_exit_raw"]
        funding = selected[item["exit"] + "_funding"]
        fill = raw * (1 - selected.side * slip)
        net = selected.side * (fill - selected.entry_fill) / selected.entry_fill - .0005 * (1 + fill / selected.entry_fill) - funding
        assert int((net > 0).sum()) == item["wins"]
        assert abs(100 * (net > 0).mean() - item["win_rate_pct"]) < 1e-10
        assert abs(100 * net.mean() - item["mean_net_pct_notional"]) < 1e-10
        if (net < 0).any():
            assert abs(net[net > 0].sum() / -net[net < 0].sum() - item["profit_factor"]) < 1e-10
    combined = []
    for lev in (10, 20):
        selected = cases[(cases.leverage == lev) & (cases.gate == "pass")]
        fill = selected.trailing_exit_raw * (1 - selected.side * .0005)
        net = selected.side * (fill - selected.entry_fill) / selected.entry_fill - .0005 * (1 + fill / selected.entry_fill) - selected.trailing_funding
        parts = [x for x in result["rows"] if x["leverage"] == lev and x["gate"] == "strong"
                 and x["exit"] == "trailing" and x["exit_slippage_pct"] == .05]
        assert len(parts) == 3 and sum(x["trades"] for x in parts) == len(selected) and sum(x["wins"] for x in parts) == int((net > 0).sum())
        weighted = sum(x["trades"] * x["mean_net_pct_notional"] for x in parts) / len(selected)
        assert abs(weighted - 100 * net.mean()) < 1e-10
        combined.append({"leverage": lev, "trades": len(selected), "wins": int((net > 0).sum()),
                         "win_rate_pct": float(100 * (net > 0).mean()), "mean_net_pct_notional": float(100 * net.mean())})
    out = {"all_checks_pass": True, "candidate_paths_checked": checked, "groups_checked": len(result["rows"]), "combined": combined,
           "result_sha256": bulk.sha(H / "强方向组合结果.json"), "code_sha256": bulk.sha(Path(__file__)),
           "note": "Independent inequality, timestamps, source-path joins and vectorized net arithmetic."}
    (H / "强方向组合独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
