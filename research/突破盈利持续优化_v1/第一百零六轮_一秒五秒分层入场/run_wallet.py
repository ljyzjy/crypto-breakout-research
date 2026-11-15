"""Known-path wallet scenarios for the staged-entry experiment."""
from __future__ import annotations

import csv
from decimal import Decimal
import importlib.util
import json
from pathlib import Path

from run_staged import H, POLICIES, load_year, sha
from wallet_engine_param import simulate

D = Decimal
R85 = H.parent / "第八十五轮_共享资金条件模拟"


def main():
    unit = json.loads((H / "分层入场单位结果.json").read_text(encoding="utf-8"))
    audit = json.loads((H / "分层入场独立核验.json").read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["result_sha256"] == sha(H / "分层入场单位结果.json")
    assert audit["audit_code_sha256"] == sha(H / "audit_staged.py")
    assert unit["detail_sha256"] == sha(H / "分层入场逐候选明细.csv")
    test = json.loads((H / "钱包参数合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["engine_sha256"] == sha(H / "wallet_engine_param.py")
    assert test["test_code_sha256"] == sha(H / "test_wallet_param.py")
    source_engine = R85 / "wallet_simulator.py"
    original_test = json.loads((R85 / "钱包时序合成核验.json").read_text(encoding="utf-8"))
    assert original_test["all_checks_pass"] and original_test["engine_sha256"] == sha(source_engine)
    assert test["original_engine_sha256"] == sha(source_engine)
    spec = importlib.util.spec_from_file_location("previous_wallet", source_engine)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    with (H / "分层入场逐候选明细.csv").open(encoding="utf-8", newline="") as stream:
        details = list(csv.DictReader(stream))
    prepared, summaries, outcomes, journals = [], [], [], []
    for year in ("2024", "2026"):
        early, late, early_map, late_map, alt_map, _, _ = load_year(year)
        for lev in (10, 20):
            for policy in POLICIES:
                selected = [x for x in details if x["year"] == year and int(x["leverage"]) == lev
                            and x["policy"] == policy and x["status"] == "trade"]
                records = []
                for x in selected:
                    obs, branch, target = x["observation_id"], x["branch"], int(x["target_r"])
                    signal = (early if branch == "early" else late).loc[obs].to_dict()
                    if branch == "late":
                        p = late_map[(obs, f"normal_2r_{lev}x")]
                    elif target == 1:
                        p = alt_map[(obs, f"one_observation_1r_{lev}x")]
                    else:
                        p = early_map[(obs, f"one_observation_2r_{lev}x")]
                    funding = json.loads(p["funding_events_json"])
                    assert abs(sum(D(str(f["charge"])) for f in funding) - D(str(p["funding"]))) < D("1e-11")
                    assert abs(D(str(p["net_per_unit_notional"])) - D(x["net_base"])) < D("1e-11")
                    reference = signal["raw_entry_1s" if branch == "early" else "raw_entry_5s"]
                    records.append({"observation_id": obs, "side": int(p["side"]), "decision_ts": int(p["decision_ts"]),
                                    "reference_ts": int(signal["entry_exec_ts"]), "reference": str(reference),
                                    "stop": str(signal["stop_price"]), "entry_ts": int(p["entry_ts"]),
                                    "entry_fill": str(p["entry_fill"]), "exit_signal_ts": int(p["exit_signal_ts"]),
                                    "exit_ts": int(p["exit_ts"]), "exit_fill": str(p["exit_fill"]),
                                    "unit_net": str(p["net_per_unit_notional"]), "funding_events": funding})
                prepared.append({"year": year, "leverage": lev, "policy": policy, "records": records})
                for risk_label, per_trade, total in (("0.5%/1%", D(".005"), D(".01")), ("0.25%/0.5%", D(".0025"), D(".005"))):
                    for reverse in (False, True):
                        summary, positions, journal = simulate(records, lev, reverse_ties=reverse, per_trade=per_trade, total_risk=total)
                        if per_trade == D(".005"):
                            assert (summary, positions, journal) == original.simulate(records, lev, reverse_ties=reverse)
                        closed = [v for v in positions.values() if v["status"] == "closed"]
                        exceed = sum(-v["net_pnl"] > v["reference_wallet"] * per_trade for v in closed)
                        worst = max((-v["net_pnl"] / v["reference_wallet"] * 100 for v in closed if v["net_pnl"] < 0), default=D(0))
                        extra = {"year": year, "leverage": lev, "policy": policy, "risk_label": risk_label,
                                 "per_trade_fraction": str(per_trade), "total_risk_fraction": str(total), "reverse_ties": reverse}
                        summaries.append({**extra, **{k: float(v) if isinstance(v, D) else v for k, v in summary.items()},
                                          "planned_loss_exceeded_count": exceed, "worst_loss_pct_reference_wallet": float(worst)})
                        for obs, value in positions.items():
                            outcomes.append({**extra, "observation_id": obs,
                                             **{k: value.get(k, "") for k in ("status", "quantity", "net_pnl", "planned_risk",
                                                                                 "reference_wallet", "estimated_entry", "margin", "open_fee", "funding_paid")}})
                        journals.extend({**extra, **j} for j in journal)
    inputs = H / "钱包已知输入.json"
    inputs.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, data in (("共享钱包逐笔.csv", outcomes), ("共享钱包事件.csv", journals)):
        with (H / name).open("w", encoding="utf-8", newline="") as stream:
            w = csv.DictWriter(stream, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
    output = {"rows": summaries, "inputs_sha256": sha(inputs), "outcomes_sha256": sha(H / "共享钱包逐笔.csv"),
              "journal_sha256": sha(H / "共享钱包事件.csv"), "unit_result_sha256": sha(H / "分层入场单位结果.json"),
              "unit_audit_sha256": sha(H / "分层入场独立核验.json"), "plan_sha256": sha(H / "共享钱包研究方案.md"),
              "engine_sha256": sha(H / "wallet_engine_param.py"), "test_sha256": sha(H / "钱包参数合成核验.json"),
              "source_engine_sha256": sha(source_engine), "code_sha256": sha(Path(__file__)),
              "note": "Conditional known paths; unknowns excluded and realized-wallet drawdown ignores floating equity."}
    (H / "共享钱包情景结果.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in summaries:
        if r["leverage"] == 20 and not r["reverse_ties"] and r["policy"] in ("early_2r", "staged_2r", "staged_adaptive"):
            print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
