"""Reconstruct decisions and unit summaries from frozen input paths."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R62 = P / "第六十二轮_一秒观察更早突破"
R70 = P / "第七十轮_一秒观察一倍止盈"
D = Decimal


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def classify(row, lev):
    if row["status"] in {"first_direction_ineligible", "no_order_time", "flow_filter_not_met", "known_risk_rejected"}:
        return "rejected"
    if row["status"] != "qualified" or pd.isna(row.get(f"precheck_{lev}x")):
        return "unknown"
    return "entered" if row[f"precheck_{lev}x"] == "passed" else "rejected"


def main():
    result_path = H / "分层入场单位结果.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["detail_sha256"] == sha(H / "分层入场逐候选明细.csv")
    assert result["plan_sha256"] == sha(H / "研究方案.md")
    assert result["code_sha256"] == sha(H / "run_staged.py")
    test = json.loads((H / "合成时序核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["code_sha256"] == result["code_sha256"]
    assert test["test_sha256"] == sha(H / "test_staged.py")
    with (H / "分层入场逐候选明细.csv").open(encoding="utf-8", newline="") as stream:
        details = list(csv.DictReader(stream))
    checked = 0
    for year in ("2024", "2026"):
        snap = R62 / f"{year}完整批次_冻结"
        mf = json.loads((snap / "完整快照哈希.json").read_text(encoding="utf-8"))
        assert sha(snap / "完整快照哈希.json") == result["input_sha256"][year]["snapshot_manifest"]
        inputs = json.loads((snap / f"support/{year}输入冻结哈希.json").read_text(encoding="utf-8"))
        for filename in ("batch/动态池逐笔信号筛查.parquet", "batch/动态池单位收益与风险.parquet",
                         f"support/{year}输入冻结哈希.json"):
            assert sha(snap / filename) == mf["files"][filename]
        old = {}
        for filename in ("baseline_signal.parquet", "baseline_ledger.parquet"):
            p = snap / "input" / filename
            if not p.exists():
                p = R62 / f"{year}冻结输入" / filename
                assert sha(p) == inputs["input_sha256"][filename]
            else:
                assert sha(p) == mf["files"][f"input/{filename}"]
            old[filename] = p
        assert sha(old["baseline_signal.parquet"]) == result["input_sha256"][year]["old_signal"]
        assert sha(old["baseline_ledger.parquet"]) == result["input_sha256"][year]["old_ledger"]
        es = {r["observation_id"]: r for r in pd.read_parquet(snap / "batch/动态池逐笔信号筛查.parquet").to_dict("records")}
        ls = {r["observation_id"]: r for r in pd.read_parquet(old["baseline_signal.parquet"]).to_dict("records")}
        epaths = {(r["observation_id"], r["variant"]): r for r in pd.read_parquet(snap / "batch/动态池单位收益与风险.parquet").to_dict("records")}
        lpaths = {(r["observation_id"], r["variant"]): r for r in pd.read_parquet(old["baseline_ledger.parquet"]).to_dict("records")}
        risk_path = R70 / f"{year}一倍止盈本地风险账本.json"
        risk_audit = R70 / f"{year}一倍止盈账本独立核验.json"
        tape_audit = R70 / f"{year}一倍止盈逐笔独立核验.json"
        assert sha(risk_path) == result["input_sha256"][year]["risk_1r"]
        assert sha(risk_audit) == result["input_sha256"][year]["risk_1r_audit"]
        assert sha(tape_audit) == result["input_sha256"][year]["tape_1r_audit"]
        risk = json.loads(risk_path.read_text(encoding="utf-8"))
        proof = json.loads(risk_audit.read_text(encoding="utf-8"))
        assert proof["all_checks_pass"] and proof["ledger_sha256"] == sha(risk_path)
        assert json.loads(tape_audit.read_text(encoding="utf-8"))["all_checks_pass"]
        apaths = {(r["observation_id"], r["variant"]): r for r in risk["records"]}
        for lev in (10, 20):
            subset = [r for r in details if r["year"] == year and int(r["leverage"]) == lev]
            assert len(subset) == len(es) * 5
            assert len({(r["observation_id"], r["policy"]) for r in subset}) == len(subset)
            for row in subset:
                obs, policy = row["observation_id"], row["policy"]
                e, l = es[obs], ls[obs]
                e_state, l_state = classify(e, lev), classify(l, lev)
                assert (row["early_status"], row["early_state"], row["late_status"], row["late_state"]) == (
                    e["status"], e_state, l["status"], l_state)
                if policy == "early_2r":
                    expected = {"entered": "early", "rejected": "no_order", "unknown": "unknown"}[e_state]
                elif policy == "late_2r":
                    expected = {"entered": "late", "rejected": "no_order", "unknown": "unknown"}[l_state]
                elif e_state == "entered":
                    expected = "early"
                elif e_state == "unknown" or l_state == "unknown":
                    expected = "unknown"
                elif l_state == "rejected":
                    expected = "no_order"
                elif pd.isna(e.get("entry_exec_ts")) or pd.isna(l.get("entry_exec_ts")) or int(e["entry_exec_ts"]) > int(l["entry_exec_ts"]):
                    expected = "unknown"
                else:
                    expected = "late"
                assert row["branch"] == expected
                if policy.startswith("staged_") and expected == "unknown" and e_state == "rejected" and l_state == "entered":
                    assert row["reason"] == "late_confirmation_before_early_rejection"
                if expected in ("early", "late"):
                    target = 2
                    if expected == "early" and policy == "staged_1r":
                        target = 1
                    elif expected == "early" and policy == "staged_adaptive" and D(str(e["one_imbalance"])) < D("0.5"):
                        target = 1
                    assert int(row["target_r"]) == target
                    if expected == "late":
                        path = lpaths.get((obs, f"normal_2r_{lev}x"))
                        signal = l
                    elif target == 1:
                        path = apaths.get((obs, f"one_observation_1r_{lev}x"))
                        signal = e
                        paired = epaths[(obs, f"one_observation_2r_{lev}x")]
                        assert path is not None and path["entry_ts"] == paired["entry_ts"] and path["side"] == paired["side"]
                        assert abs(D(str(path["entry_fill"])) - D(str(paired["entry_fill"]))) < D("1e-9")
                    else:
                        path = epaths.get((obs, f"one_observation_2r_{lev}x"))
                        signal = e
                    verified = bool(path and path.get("status") == "verified" and path.get("risk_status") == "verified"
                                    and not pd.isna(path.get("liq_proxy")) and not bool(path["liq_proxy"]))
                    if not verified:
                        assert row["status"] == "unknown" and row["reason"] == "entered_path_or_risk_unknown"
                    else:
                        assert row["status"] == "trade"
                        assert int(row["entry_ts"]) == int(path["entry_ts"])
                        assert int(row["entry_ts"]) >= int(signal["entry_exec_ts"]) + (1000 if expected == "early" else 5000)
                        assert int(path["exit_ts"]) >= int(path["exit_signal_ts"]) + 5000
                        for k in ("entry_fill", "exit_raw", "funding", "side"):
                            assert D(row[k]) == D(str(path[k]))
                        for column, slip in (("net_base", D(".0005")), ("net_s075", D(".00075")), ("net_s100", D(".001"))):
                            side, entry = D(str(path["side"])), D(str(path["entry_fill"]))
                            filled = D(str(path["exit_raw"])) * (1 - side * slip)
                            pnl = side * (filled / entry - 1) - D(".0005") * (1 + filled / entry) - D(str(path["funding"]))
                            assert abs(pnl - D(row[column])) < D("1e-20")
                else:
                    assert row["status"] == expected
                checked += 1
            for group in [x for x in result["rows"] if x["year"] == year and x["leverage"] == lev]:
                all_rows = [r for r in subset if r["policy"] == group["policy"]]
                good = [r for r in all_rows if r["status"] == "trade"]
                col = {0.05: "net_base", 0.075: "net_s075", 0.1: "net_s100"}[group["exit_slippage_pct"]]
                vals = [D(r[col]) for r in good]
                wins = sum(v > 0 for v in vals)
                days = {datetime.fromtimestamp(int(r["entry_ts"]) / 1000, timezone.utc).date() for r in good}
                assert (group["candidates"], group["trades"], group["wins"], group["active_utc_days"]) == (len(all_rows), len(good), wins, len(days))
                assert group["unknown"] == sum(r["status"] == "unknown" for r in all_rows)
                assert group["unknown_time_order"] == sum(r["reason"] == "late_confirmation_before_early_rejection" for r in all_rows)
                assert group["no_order"] == sum(r["status"] == "no_order" for r in all_rows)
                assert group["early_trades"] == sum(r["status"] == "trade" and r["branch"] == "early" for r in all_rows)
                assert group["late_trades"] == sum(r["status"] == "trade" and r["branch"] == "late" for r in all_rows)
                if vals:
                    assert abs(D(str(group["win_rate_pct"])) - D(100) * wins / len(vals)) < D("1e-12")
                    assert abs(D(str(group["mean_net_pct_notional"])) - D(100) * sum(vals) / len(vals)) < D("1e-12")
                    profit = sum(v for v in vals if v > 0)
                    loss = -sum(v for v in vals if v < 0)
                    if loss:
                        assert abs(D(str(group["profit_factor"])) - profit / loss) < D("1e-12")
                    else:
                        assert group["profit_factor"] is None
    out = {"all_checks_pass": True, "candidate_policy_decisions_checked": checked,
           "groups_checked": len(result["rows"]), "result_sha256": sha(result_path),
           "detail_sha256": sha(H / "分层入场逐候选明细.csv"), "audit_code_sha256": sha(Path(__file__)),
           "note": "Source joins, time ordering and cost arithmetic independently reconstructed; no shared-account or real fills."}
    (H / "分层入场独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
