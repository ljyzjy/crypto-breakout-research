"""Independently reconstruct each retry decision and its net outcome."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R47 = P / "第四十七轮_一次重新突破确认"
R106 = P / "第一百零六轮_一秒五秒分层入场"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def timestamp(v):
    try:
        d = D(str(v))
        return int(d) if d.is_finite() else None
    except Exception:
        return None


def main():
    result_path = H / "早入重突单位结果.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["detail_sha256"] == sha(H / "早入重突逐候选.csv")
    assert result["freeze_sha256"] == sha(H / "输入冻结.json")
    assert result["code_sha256"] == sha(H / "run_retry_combo.py")
    assert result["test_sha256"] == sha(H / "合成时序核验.json")
    test = json.loads((H / "合成时序核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["code_sha256"] == result["code_sha256"]
    assert test["test_sha256"] == sha(H / "test_retry_combo.py")
    freeze = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert freeze["freeze_code_sha256"] == sha(H / "freeze_inputs.py")
    for filename, digest in freeze["files"].items():
        assert sha(Path(filename)) == digest
    with (R106 / "分层入场逐候选明细.csv").open(encoding="utf-8", newline="") as f:
        original = {(r["year"], int(r["leverage"]), r["observation_id"]): r
                    for r in csv.DictReader(f) if r["policy"] == "staged_2r"}
    with (H / "早入重突逐候选.csv").open(encoding="utf-8", newline="") as f:
        data = list(csv.DictReader(f))
    assert len(data) == len(original) == len({(r["year"], r["leverage"], r["observation_id"]) for r in data})
    checked = added = 0
    for year in ("2024", "2026"):
        folder = R47 / f"{year}重试分批"
        signals = {r["observation_id"]: r for r in pd.read_parquet(folder / "动态池逐笔信号筛查.parquet").to_dict("records")}
        paths = {(r["observation_id"], r["variant"]): r for r in pd.read_parquet(folder / "动态池单位收益与风险.parquet").to_dict("records")}
        retry_candidates = pd.read_parquet(R47 / "跨期冻结输入" / f"{year}_retry_candidates.parquet")
        assert set(signals) == set(retry_candidates.observation_id)
        for lev in (10, 20):
            subset = [r for r in data if r["year"] == year and int(r["leverage"]) == lev]
            for row in subset:
                obs = row["observation_id"]
                before = original[(year, lev, obs)]
                signal = signals.get(obs)
                assert row["previous_status"] == before["status"]
                if signal is None:
                    assert row["retry_signal_status"] == "not_candidate" and row["retry_state"] == "not_candidate"
                    choice = "prior" if before["status"] != "no_order" else "no_order"
                else:
                    assert row["retry_signal_status"] == signal["status"]
                    if signal["status"] in {"no_retest_known", "retest_flow_filter_not_met", "no_order_time", "known_risk_rejected"}:
                        retry_state = "rejected"
                    elif signal["status"] != "qualified" or pd.isna(signal.get(f"precheck_{lev}x")):
                        retry_state = "unknown"
                    else:
                        retry_state = "entered" if signal[f"precheck_{lev}x"] == "passed" else "rejected"
                    assert row["retry_state"] == retry_state
                    if before["status"] != "no_order":
                        choice = "prior"
                    elif retry_state == "unknown":
                        choice = "unknown"
                    elif retry_state == "rejected":
                        choice = "no_order"
                    else:
                        e = timestamp(before["early_ref_ts"])
                        old = timestamp(before["late_ref_ts"])
                        cross = timestamp(signal.get("retest_ts"))
                        ref = timestamp(signal.get("entry_exec_ts"))
                        choice = "retry" if all(v is not None for v in (e, old, cross, ref)) and e <= ref and old < cross and cross + 5000 <= ref else "unknown"
                assert row["retry_decision"] == choice
                if choice == "prior":
                    assert row["status"] == before["status"] and row["branch"] == before["branch"]
                    for col in ("entry_ts", "entry_fill", "exit_ts", "exit_raw", "side", "funding", "net_base", "net_s075", "net_s100"):
                        assert row[col] == before[col]
                elif choice == "no_order":
                    assert row["status"] == "no_order"
                elif choice == "unknown":
                    assert row["status"] == "unknown"
                else:
                    assert before["early_state"] == "rejected" and before["late_status"] == "flow_filter_not_met"
                    assert timestamp(signal["entry_exec_ts_original"]) == timestamp(before["late_ref_ts"])
                    assert timestamp(signal["first_decision_ts"]) == timestamp(signal["decision_ts_original"])
                    assert timestamp(signal["retest_ts"]) == timestamp(signal["decision_ts"])
                    path = paths.get((obs, f"normal_2r_{lev}x"))
                    verified = bool(path and path.get("status") == "verified" and path.get("risk_status") == "verified"
                                    and not pd.isna(path.get("liq_proxy")) and not bool(path["liq_proxy"]))
                    if not verified:
                        assert row["status"] == "unknown" and row["reason"] == "retry_path_or_risk_unknown"
                    else:
                        assert row["status"] == "trade" and row["branch"] == "retry"
                        assert int(path["entry_signal_reference_ts"]) == int(signal["entry_exec_ts"])
                        assert int(path["entry_ts"]) >= int(signal["entry_exec_ts"]) + 5000
                        assert int(path["exit_ts"]) >= int(path["exit_signal_ts"]) + 5000
                        assert int(row["entry_ts"]) == int(path["entry_ts"]) and int(row["exit_ts"]) == int(path["exit_ts"])
                        for key in ("entry_fill", "exit_raw", "side", "funding"):
                            assert D(row[key]) == D(str(path[key]))
                        for col, slip in (("net_base", D(".0005")), ("net_s075", D(".00075")), ("net_s100", D(".001"))):
                            entry, side = D(str(path["entry_fill"])), D(str(path["side"]))
                            exit_ = D(str(path["exit_raw"])) * (1 - side * slip)
                            net = side * (exit_ / entry - 1) - D(".0005") * (1 + exit_ / entry) - D(str(path["funding"]))
                            assert abs(net - D(row[col])) < D("1e-20")
                        added += 1
                checked += 1
            for group in [x for x in result["rows"] if x["year"] == year and x["leverage"] == lev]:
                trades = [r for r in subset if r["status"] == "trade"]
                col = {0.05: "net_base", 0.075: "net_s075", 0.1: "net_s100"}[group["exit_slippage_pct"]]
                vals = [D(r[col]) for r in trades]
                wins = sum(v > 0 for v in vals)
                days = {datetime.fromtimestamp(int(r["entry_ts"]) / 1000, timezone.utc).date() for r in trades}
                assert (group["candidates"], group["trades"], group["wins"], group["active_utc_days"]) == (len(subset), len(trades), wins, len(days))
                assert group["unknown"] == sum(r["status"] == "unknown" for r in subset)
                assert group["no_order"] == sum(r["status"] == "no_order" for r in subset)
                assert group["retry_timing_unknown"] == sum(r["reason"] == "retry_timing_unverified" for r in subset)
                for branch in ("early", "late", "retry"):
                    assert group[f"{branch}_trades"] == sum(r["branch"] == branch for r in trades)
                if vals:
                    assert abs(D(str(group["win_rate_pct"])) - D(100) * wins / len(vals)) < D("1e-12")
                    assert abs(D(str(group["mean_net_pct_notional"])) - D(100) * sum(vals) / len(vals)) < D("1e-12")
                    pos, neg = sum(v for v in vals if v > 0), -sum(v for v in vals if v < 0)
                    if neg:
                        assert abs(D(str(group["profit_factor"])) - pos / neg) < D("1e-12")
                    else:
                        assert group["profit_factor"] is None
    out = {"all_checks_pass": True, "candidate_decisions_checked": checked, "retry_paths_checked": added,
           "summary_groups_checked": len(result["rows"]), "result_sha256": sha(result_path),
           "detail_sha256": sha(H / "早入重突逐候选.csv"), "audit_code_sha256": sha(Path(__file__)),
           "note": "Historical unit paths only; source retry mark-price proof inherited and independently net-checked."}
    (H / "早入重突独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
