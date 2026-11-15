"""Compare known staged paths against their single-rebreakout extension."""
from __future__ import annotations

import csv
from decimal import Decimal as D
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R47 = P / "第四十七轮_一次重新突破确认"
R106 = P / "第一百零六轮_一秒五秒分层入场"
sys.path.insert(0, str(R106))
from run_staged import sha
from wallet_engine_param import simulate


def main():
    unit_audit = json.loads((H / "早入重突独立核验.json").read_text(encoding="utf-8"))
    assert unit_audit["all_checks_pass"] and unit_audit["result_sha256"] == sha(H / "早入重突单位结果.json")
    assert unit_audit["audit_code_sha256"] == sha(H / "audit_retry_combo.py")
    base = json.loads((R106 / "共享钱包情景结果.json").read_text(encoding="utf-8"))
    base_audit = json.loads((R106 / "共享钱包独立核验.json").read_text(encoding="utf-8"))
    assert base_audit["all_checks_pass"] and base_audit["result_sha256"] == sha(R106 / "共享钱包情景结果.json")
    assert base["inputs_sha256"] == sha(R106 / "钱包已知输入.json")
    assert base["engine_sha256"] == sha(R106 / "wallet_engine_param.py")
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    for filename, digest in frozen["files"].items():
        assert sha(Path(filename)) == digest
    with (H / "早入重突逐候选.csv").open(encoding="utf-8", newline="") as stream:
        detail = list(csv.DictReader(stream))
    previous = json.loads((R106 / "钱包已知输入.json").read_text(encoding="utf-8"))
    prepared, summaries, positions_out, journal_out = [], [], [], []
    for year in ("2024", "2026"):
        folder = R47 / f"{year}重试分批"
        signals = pd.read_parquet(folder / "动态池逐笔信号筛查.parquet").set_index("observation_id").to_dict("index")
        source = pd.read_parquet(folder / "动态池单位收益与风险.parquet").to_dict("records")
        paths = {(r["observation_id"], r["variant"]): r for r in source}
        for lev in (10, 20):
            prior = next(x for x in previous if x["year"] == year and x["leverage"] == lev and x["policy"] == "staged_2r")
            records = [dict(r) for r in prior["records"]]
            selected = [r for r in detail if r["year"] == year and int(r["leverage"]) == lev and r["status"] == "trade"]
            old_ids = {r["observation_id"] for r in records}
            assert old_ids == {r["observation_id"] for r in selected if r["branch"] != "retry"}
            for item in selected:
                if item["branch"] != "retry":
                    continue
                obs, signal = item["observation_id"], signals[item["observation_id"]]
                path = paths[(obs, f"normal_2r_{lev}x")]
                assert path["status"] == path["risk_status"] == "verified" and not bool(path["liq_proxy"])
                funding = json.loads(path["funding_events_json"])
                assert abs(sum((D(str(x["charge"])) for x in funding), D(0)) - D(str(path["funding"]))) < D("1e-11")
                assert abs(D(str(path["net_per_unit_notional"])) - D(item["net_base"])) < D("1e-11")
                records.append({"observation_id": obs, "side": int(path["side"]), "decision_ts": int(path["decision_ts"]),
                                "reference_ts": int(signal["entry_exec_ts"]), "reference": str(signal["raw_entry_5s"]),
                                "stop": str(signal["stop_price"]), "entry_ts": int(path["entry_ts"]),
                                "entry_fill": str(path["entry_fill"]), "exit_signal_ts": int(path["exit_signal_ts"]),
                                "exit_ts": int(path["exit_ts"]), "exit_fill": str(path["exit_fill"]),
                                "unit_net": str(path["net_per_unit_notional"]), "funding_events": funding})
            assert len(records) == len(selected) == len({r["observation_id"] for r in records})
            prepared.append({"year": year, "leverage": lev, "records": records})
            for risk_label, per_trade, total in (("0.5%/1%", D(".005"), D(".01")), ("0.25%/0.5%", D(".0025"), D(".005"))):
                for reverse in (False, True):
                    summary, positions, journal = simulate(records, lev, reverse_ties=reverse, per_trade=per_trade, total_risk=total)
                    old = next(x for x in base["rows"] if x["year"] == year and x["leverage"] == lev and x["policy"] == "staged_2r"
                               and x["risk_label"] == risk_label and x["reverse_ties"] == reverse)
                    closed = [v for v in positions.values() if v["status"] == "closed"]
                    exceed = sum(-v["net_pnl"] > v["reference_wallet"] * per_trade for v in closed)
                    worst = max((-v["net_pnl"] / v["reference_wallet"] * 100 for v in closed if v["net_pnl"] < 0), default=D(0))
                    extra = {"year": year, "leverage": lev, "risk_label": risk_label,
                             "per_trade_fraction": str(per_trade), "total_risk_fraction": str(total), "reverse_ties": reverse}
                    summaries.append({**extra, **{k: float(v) if isinstance(v, D) else v for k, v in summary.items()},
                                      "planned_loss_exceeded_count": exceed, "worst_loss_pct_reference_wallet": float(worst),
                                      "baseline_final_wallet": old["final_wallet"], "baseline_trades": old["simulated_trades"]})
                    for obs, value in positions.items():
                        positions_out.append({**extra, "observation_id": obs,
                                              **{k: value.get(k, "") for k in ("status", "quantity", "net_pnl", "planned_risk",
                                                                                  "reference_wallet", "estimated_entry", "margin", "open_fee", "funding_paid")}})
                    journal_out.extend({**extra, **j} for j in journal)
    inputs = H / "钱包已知输入.json"
    inputs.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, data in (("共享钱包逐笔.csv", positions_out), ("共享钱包事件.csv", journal_out)):
        with (H / name).open("w", encoding="utf-8", newline="") as stream:
            w = csv.DictWriter(stream, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
    result = {"rows": summaries, "inputs_sha256": sha(inputs), "outcomes_sha256": sha(H / "共享钱包逐笔.csv"),
              "journal_sha256": sha(H / "共享钱包事件.csv"), "unit_result_sha256": sha(H / "早入重突单位结果.json"),
              "unit_audit_sha256": sha(H / "早入重突独立核验.json"), "baseline_result_sha256": sha(R106 / "共享钱包情景结果.json"),
              "baseline_audit_sha256": sha(R106 / "共享钱包独立核验.json"), "plan_sha256": sha(H / "共享钱包研究方案.md"),
              "engine_sha256": sha(R106 / "wallet_engine_param.py"), "code_sha256": sha(Path(__file__)),
              "note": "Known historical paths only; unknowns omitted and floating equity excluded."}
    (H / "共享钱包情景结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in summaries:
        if row["leverage"] == 20 and not row["reverse_ties"]:
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
