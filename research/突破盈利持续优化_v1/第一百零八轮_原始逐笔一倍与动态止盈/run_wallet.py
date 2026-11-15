"""Shared-wallet comparison of same known 2022 raw entry paths."""
from __future__ import annotations

import csv
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R106 = P / "第一百零六轮_一秒五秒分层入场"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(R106))
from wallet_engine_param import simulate
spec = importlib.util.spec_from_file_location("ext98_wallet_108", R98 / "run_wallet.py")
old_wallet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old_wallet)


def main():
    bulk.runner.guard(start=True)
    unit = json.loads((H / "一倍动态结果汇总.json").read_text(encoding="utf-8"))
    audit = json.loads((H / "一倍动态汇总独立核验.json").read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["result_sha256"] == bulk.sha(H / "一倍动态结果汇总.json")
    assert audit["code_sha256"] == bulk.sha(H / "audit_summary.py")
    prior = json.loads((R98 / "共享钱包独立核验.json").read_text(encoding="utf-8"))
    assert prior["all_checks_pass"] and prior["result_sha256"] == bulk.sha(R98 / "共享钱包情景汇总.json")
    test = json.loads((R106 / "钱包参数合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["engine_sha256"] == bulk.sha(R106 / "wallet_engine_param.py")
    assert test["test_code_sha256"] == bulk.sha(R106 / "test_wallet_param.py")
    test_audit = json.loads((R106 / "共享钱包独立核验.json").read_text(encoding="utf-8"))
    assert test_audit["all_checks_pass"] and test_audit["result_sha256"] == bulk.sha(R106 / "共享钱包情景结果.json")
    with (H / "一倍动态配对明细.csv").open(encoding="utf-8", newline="") as stream:
        pairs = list(csv.DictReader(stream))
    alt = pd.read_parquet(H / "一倍止盈单位账本.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    originals = old_wallet.load_records()
    originals = {(r["observation_id"], r["leverage"]): r for r in originals}
    prepared, summaries, positions_out, journal_out = [], [], [], []
    for lev in (10, 20):
        cohort_pairs = [r for r in pairs if int(r["leverage"]) == lev]
        for cohort in ("baseline_paired", "one_r", "adaptive"):
            records = []
            for pair in cohort_pairs:
                obs = pair["observation_id"]
                orig = originals[(obs, lev)]
                selected = alt[(obs, orig["variant"])] if cohort == "one_r" or (cohort == "adaptive" and pair["adaptive_target"] == "1r") else None
                r = dict(orig)
                if selected is not None:
                    assert selected["risk_status"] == "verified" and not bool(selected["liq_proxy"])
                    events = json.loads(selected["funding_events_json"])
                    assert abs(sum((D(str(f["charge"])) for f in events), D(0)) - D(str(selected["funding"]))) < D("1e-11")
                    r.update(exit_signal_ts=int(selected["exit_signal_ts"]), exit_ts=int(selected["exit_ts"]),
                             exit_fill=str(selected["exit_fill"]), unit_net=str(selected["net_per_unit_notional"]), funding_events=events)
                assert abs(D(str(r["unit_net"])) - D(pair[{"baseline_paired": "baseline_net", "one_r": "one_r_net", "adaptive": "adaptive_net"}[cohort]])) < D("1e-11")
                records.append(r)
            prepared.append({"leverage": lev, "cohort": cohort, "records": records})
            for risk_label, one, total in (("0.5%/1%", D(".005"), D(".01")), ("0.25%/0.5%", D(".0025"), D(".005"))):
                for reverse in (False, True):
                    summary, positions, journal = simulate(records, lev, reverse_ties=reverse, per_trade=one, total_risk=total)
                    if one == D(".005"):
                        assert (summary, positions, journal) == old_wallet.simulate(records, lev, reverse_ties=reverse)
                    closed = [v for v in positions.values() if v["status"] == "closed"]
                    exceeded = sum(-v["net_pnl"] > v["reference_wallet"] * one for v in closed)
                    worst = max((-v["net_pnl"] / v["reference_wallet"] * 100 for v in closed if v["net_pnl"] < 0), default=D(0))
                    extra = {"leverage": lev, "cohort": cohort, "risk_label": risk_label,
                             "per_trade_fraction": str(one), "total_risk_fraction": str(total), "reverse_ties": reverse}
                    summaries.append({**extra, **{k: float(v) if isinstance(v, D) else v for k, v in summary.items()},
                                      "planned_loss_exceeded_count": exceeded, "worst_loss_pct_reference_wallet": float(worst)})
                    for obs, p in positions.items():
                        positions_out.append({**extra, "observation_id": obs,
                                              **{k: p.get(k, "") for k in ("status", "quantity", "net_pnl", "planned_risk", "reference_wallet",
                                                                             "estimated_entry", "margin", "open_fee", "funding_paid")}})
                    journal_out.extend({**extra, **j} for j in journal)
    inputs = H / "钱包已知输入.json"
    inputs.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, data in (("共享钱包逐笔.csv", positions_out), ("共享钱包事件.csv", journal_out)):
        with (H / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    result = {"rows": summaries, "inputs_sha256": bulk.sha(inputs), "outcomes_sha256": bulk.sha(H / "共享钱包逐笔.csv"),
              "journal_sha256": bulk.sha(H / "共享钱包事件.csv"), "unit_result_sha256": bulk.sha(H / "一倍动态结果汇总.json"),
              "unit_audit_sha256": bulk.sha(H / "一倍动态汇总独立核验.json"), "plan_sha256": bulk.sha(H / "共享钱包研究方案.md"),
              "engine_sha256": bulk.sha(R106 / "wallet_engine_param.py"), "engine_test_sha256": bulk.sha(R106 / "钱包参数合成核验.json"),
              "original_wallet_audit_sha256": bulk.sha(R98 / "共享钱包独立核验.json"), "code_sha256": bulk.sha(Path(__file__)),
              "unknown_rank_hours": 240, "note": "Known paired 2022 paths only; unknowns omitted and floating equity excluded."}
    (H / "共享钱包情景结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in summaries:
        if row["leverage"] == 20 and not row["reverse_ties"]:
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
