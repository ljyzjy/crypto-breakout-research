"""Combine staged entries with one historically replayed rebreakout, without peeking."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R47 = P / "第四十七轮_一次重新突破确认"
R106 = P / "第一百零六轮_一秒五秒分层入场"
sys.path.insert(0, str(R106))
from run_staged import net_value


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ms(value):
    try:
        x = D(str(value))
        return int(x) if x.is_finite() else None
    except Exception:
        return None


def state(r, lev):
    if r["status"] in {"no_retest_known", "retest_flow_filter_not_met", "no_order_time", "known_risk_rejected"}:
        return "rejected"
    if r["status"] != "qualified" or pd.isna(r.get(f"precheck_{lev}x")):
        return "unknown"
    return "entered" if r[f"precheck_{lev}x"] == "passed" else "rejected"


def retry_decision(prior, exists, retry_state, early_ref, old_ref, retest_ts, retry_ref):
    if prior != "no_order":
        return "prior", "keep_existing_result"
    if not exists:
        return "no_order", "not_eligible_for_retry"
    if retry_state == "unknown":
        return "unknown", "retry_signal_unknown"
    if retry_state == "rejected":
        return "no_order", "retry_rejected"
    e, old, cross, ref = map(ms, (early_ref, old_ref, retest_ts, retry_ref))
    if any(v is None for v in (e, old, cross, ref)) or not (e <= ref and old < cross and cross + 5000 <= ref):
        return "unknown", "retry_timing_unverified"
    return "retry", "one_rebreakout"


def summary(rows, col):
    trades = [r for r in rows if r["status"] == "trade"]
    v = [D(r[col]) for r in trades]
    positive = sum((x for x in v if x > 0), D(0))
    negative = -sum((x for x in v if x < 0), D(0))
    return {"candidates": len(rows), "trades": len(v), "wins": sum(x > 0 for x in v),
            "win_rate_pct": float(D(100) * sum(x > 0 for x in v) / len(v)) if v else None,
            "mean_net_pct_notional": float(D(100) * sum(v, D(0)) / len(v)) if v else None,
            "profit_factor": float(positive / negative) if negative else None,
            "active_utc_days": len({datetime.fromtimestamp(int(r["entry_ts"]) / 1000, timezone.utc).date() for r in trades}),
            "unknown": sum(r["status"] == "unknown" for r in rows), "no_order": sum(r["status"] == "no_order" for r in rows),
            "retry_timing_unknown": sum(r["reason"] == "retry_timing_unverified" for r in rows),
            "early_trades": sum(r["status"] == "trade" and r["branch"] == "early" for r in rows),
            "late_trades": sum(r["status"] == "trade" and r["branch"] == "late" for r in rows),
            "retry_trades": sum(r["status"] == "trade" and r["branch"] == "retry" for r in rows)}


def main():
    freeze = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert freeze["freeze_code_sha256"] == sha(H / "freeze_inputs.py")
    for path, digest in freeze["files"].items():
        assert sha(Path(path)) == digest
    test = json.loads((H / "合成时序核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["code_sha256"] == sha(Path(__file__)) and test["test_sha256"] == sha(H / "test_retry_combo.py")
    with (R106 / "分层入场逐候选明细.csv").open(encoding="utf-8", newline="") as stream:
        original = [x for x in csv.DictReader(stream) if x["policy"] == "staged_2r"]
    all_rows, groups = [], []
    for year in ("2024", "2026"):
        folder = R47 / f"{year}重试分批"
        signals = pd.read_parquet(folder / "动态池逐笔信号筛查.parquet").set_index("observation_id").to_dict("index")
        ledger = pd.read_parquet(folder / "动态池单位收益与风险.parquet").to_dict("records")
        paths = {(r["observation_id"], r["variant"]): r for r in ledger}
        assert len(paths) == len(ledger)
        for lev in (10, 20):
            items = [r for r in original if r["year"] == year and int(r["leverage"]) == lev]
            for old in items:
                obs = old["observation_id"]
                signal = signals.get(obs)
                retry_state = state(signal, lev) if signal else "not_candidate"
                chosen, why = retry_decision(old["status"], bool(signal), retry_state, old["early_ref_ts"], old["late_ref_ts"],
                                             signal.get("retest_ts") if signal else None, signal.get("entry_exec_ts") if signal else None)
                row = {k: old[k] for k in ("year", "leverage", "observation_id", "early_status", "early_state", "early_ref_ts",
                                          "late_status", "late_state", "late_ref_ts", "branch", "status", "reason",
                                          "entry_ts", "entry_fill", "exit_ts", "exit_raw", "side", "funding",
                                          "net_base", "net_s075", "net_s100")}
                row.update(previous_status=old["status"], retry_signal_status=signal["status"] if signal else "not_candidate",
                           retry_state=retry_state, retry_decision=chosen, retry_reason=why,
                           retest_ts=signal.get("retest_ts") if signal else "", retry_ref_ts=signal.get("entry_exec_ts") if signal else "")
                if chosen == "unknown":
                    row.update(status="unknown", branch="unknown", reason=why)
                elif chosen == "retry":
                    assert old["late_status"] == "flow_filter_not_met" and old["early_state"] == "rejected"
                    assert ms(signal["entry_exec_ts_original"]) == ms(old["late_ref_ts"])
                    assert ms(signal["first_decision_ts"]) == ms(signal["decision_ts_original"])
                    assert ms(signal["retest_ts"]) == ms(signal["decision_ts"])
                    assert int(signal["side"]) == int(signal["side_original"])
                    path = paths.get((obs, f"normal_2r_{lev}x"))
                    if not path or path["status"] != "verified" or path["risk_status"] != "verified" or pd.isna(path["liq_proxy"]) or bool(path["liq_proxy"]):
                        row.update(status="unknown", branch="unknown", reason="retry_path_or_risk_unknown")
                    else:
                        assert int(path["entry_signal_reference_ts"]) == int(signal["entry_exec_ts"])
                        assert int(path["entry_ts"]) >= int(signal["entry_exec_ts"]) + 5000
                        assert int(path["exit_ts"]) >= int(path["exit_signal_ts"]) + 5000
                        assert abs(net_value(path, D(".0005")) - D(str(path["net_per_unit_notional"]))) < D("1e-11")
                        row.update(status="trade", branch="retry", reason=why,
                                   **{k: path[k] for k in ("entry_ts", "entry_fill", "exit_ts", "exit_raw", "side", "funding")})
                        for name, slip in (("net_base", D(".0005")), ("net_s075", D(".00075")), ("net_s100", D(".001"))):
                            row[name] = str(net_value(path, slip))
                all_rows.append(row)
            selected = [r for r in all_rows if r["year"] == year and int(r["leverage"]) == lev]
            assert len(selected) == len(items)
            for col, slip in (("net_base", D(".0005")), ("net_s075", D(".00075")), ("net_s100", D(".001"))):
                groups.append({"year": year, "leverage": lev, "exit_slippage_pct": float(slip * 100), **summary(selected, col)})
    detail = H / "早入重突逐候选.csv"
    with detail.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    result = {"rows": groups, "detail_sha256": sha(detail), "freeze_sha256": sha(H / "输入冻结.json"),
              "code_sha256": sha(Path(__file__)), "test_sha256": sha(H / "合成时序核验.json"),
              "note": "Historical known unit paths; no account replay and no actual fills."}
    (H / "早入重突单位结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in groups:
        if r["leverage"] == 20 and r["exit_slippage_pct"] == .05:
            print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
