"""Recombine already verified historical paths without future-dependent branch selection."""
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
POLICIES = ("early_2r", "late_2r", "staged_2r", "staged_1r", "staged_adaptive")
SLIPS = (("net_base", Decimal("0.0005")), ("net_s075", Decimal("0.00075")),
         ("net_s100", Decimal("0.001")))


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def state(row: dict, leverage: int) -> str:
    status = row["status"]
    if status in ("first_direction_ineligible", "no_order_time", "flow_filter_not_met", "known_risk_rejected"):
        return "rejected"
    if status != "qualified":
        return "unknown"
    check = row.get(f"precheck_{leverage}x")
    if pd.isna(check):
        return "unknown"
    return "entered" if check == "passed" else "rejected"


def stage_branch(early: str, late: str, early_ref, late_ref) -> tuple[str, str]:
    if early == "entered":
        return "early", "early_order"
    if early == "unknown":
        return "unknown", "early_source_unknown"
    if late == "unknown":
        return "unknown", "late_source_unknown"
    if late == "rejected":
        return "no_order", "both_rejected"
    if pd.isna(early_ref) or pd.isna(late_ref) or int(early_ref) > int(late_ref):
        return "unknown", "late_confirmation_before_early_rejection"
    return "late", "early_rejected_then_late_order"


def choose_target(policy: str, branch: str, imbalance) -> int:
    if branch != "early" or policy in ("early_2r", "late_2r", "staged_2r"):
        return 2
    if policy == "staged_1r":
        return 1
    assert policy == "staged_adaptive" and not pd.isna(imbalance)
    flow = Decimal(str(imbalance))
    assert flow.is_finite() and flow >= Decimal("0.1")
    return 2 if flow >= Decimal("0.5") else 1


def net_value(path: dict, slip: Decimal) -> Decimal:
    entry = Decimal(str(path["entry_fill"]))
    raw_exit = Decimal(str(path["exit_raw"]))
    side = Decimal(int(path["side"]))
    funding = Decimal(str(path["funding"]))
    assert side in (Decimal(1), Decimal(-1)) and entry > 0 and raw_exit > 0 and funding.is_finite()
    exit_fill = raw_exit * (1 - side * slip)
    return side * (exit_fill - entry) / entry - Decimal("0.0005") - Decimal("0.0005") * exit_fill / entry - funding


def load_year(year: str):
    snap = R62 / f"{year}完整批次_冻结"
    mf_path = snap / "完整快照哈希.json"
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    assert mf["all_checks_pass"] is True and mf["year"] == year
    names = ("batch/动态池逐笔信号筛查.parquet", "batch/动态池单位收益与风险.parquet",
             f"support/{year}输入冻结哈希.json", f"support/{year}一秒观察对照.json")
    for name in names:
        assert sha(snap / name) == mf["files"][name]
    input_mf = json.loads((snap / names[2]).read_text(encoding="utf-8"))
    oldpaths = {}
    for name in ("baseline_signal.parquet", "baseline_ledger.parquet"):
        candidate = snap / "input" / name
        if candidate.exists():
            assert sha(candidate) == mf["files"][f"input/{name}"]
        else:
            candidate = R62 / f"{year}冻结输入" / name
            assert sha(candidate) == input_mf["input_sha256"][name]
        oldpaths[name] = candidate
    risk_path = R70 / f"{year}一倍止盈本地风险账本.json"
    risk_audit = R70 / f"{year}一倍止盈账本独立核验.json"
    tape_audit = R70 / f"{year}一倍止盈逐笔独立核验.json"
    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    audit = json.loads(risk_audit.read_text(encoding="utf-8"))
    tape = json.loads(tape_audit.read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["ledger_sha256"] == sha(risk_path)
    assert tape["all_checks_pass"] and tape["replay_fingerprint"] == risk["replay_fingerprint"]
    assert risk["source_snapshot_sha256"] == sha(mf_path)
    early = pd.read_parquet(snap / names[0]).set_index("observation_id")
    late = pd.read_parquet(oldpaths["baseline_signal.parquet"]).set_index("observation_id")
    assert early.index.is_unique and late.index.is_unique and set(early.index) == set(late.index)
    early_ledger = pd.read_parquet(snap / names[1]).to_dict("records")
    late_ledger = pd.read_parquet(oldpaths["baseline_ledger.parquet"]).to_dict("records")
    early_map = {(r["observation_id"], r["variant"]): r for r in early_ledger}
    late_map = {(r["observation_id"], r["variant"]): r for r in late_ledger}
    alt_map = {(r["observation_id"], r["variant"]): r for r in risk["records"]}
    assert len(early_map) == len(early_ledger) and len(late_map) == len(late_ledger)
    assert len(alt_map) == len(risk["records"])
    paths = {"snapshot_manifest": sha(mf_path), "risk_1r": sha(risk_path),
             "risk_1r_audit": sha(risk_audit), "tape_1r_audit": sha(tape_audit),
             "old_signal": sha(oldpaths["baseline_signal.parquet"]), "old_ledger": sha(oldpaths["baseline_ledger.parquet"])}
    ref = json.loads((snap / names[3]).read_text(encoding="utf-8"))
    return early, late, early_map, late_map, alt_map, paths, ref


def summarize(rows: list[dict], net_column: str) -> dict:
    trades = [r for r in rows if r["status"] == "trade"]
    values = [Decimal(r[net_column]) for r in trades]
    profit = sum((v for v in values if v > 0), Decimal(0))
    loss = -sum((v for v in values if v < 0), Decimal(0))
    days = {datetime.fromtimestamp(int(r["entry_ts"]) / 1000, timezone.utc).date().isoformat() for r in trades}
    return {"candidates": len(rows), "trades": len(trades), "wins": sum(v > 0 for v in values),
            "win_rate_pct": float(100 * sum(v > 0 for v in values) / len(values)) if values else None,
            "mean_net_pct_notional": float(100 * sum(values, Decimal(0)) / len(values)) if values else None,
            "profit_factor": float(profit / loss) if loss else None, "active_utc_days": len(days),
            "unknown": sum(r["status"] == "unknown" for r in rows),
            "unknown_time_order": sum(r["reason"] == "late_confirmation_before_early_rejection" for r in rows),
            "no_order": sum(r["status"] == "no_order" for r in rows),
            "early_trades": sum(r["status"] == "trade" and r["branch"] == "early" for r in rows),
            "late_trades": sum(r["status"] == "trade" and r["branch"] == "late" for r in rows)}


def main():
    test = json.loads((H / "合成时序核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["code_sha256"] == sha(Path(__file__))
    assert test["test_sha256"] == sha(H / "test_staged.py")
    rows, summary, provenance = [], [], {}
    for year in ("2024", "2026"):
        early, late, early_map, late_map, alt_map, provenance[year], ref = load_year(year)
        for lev in (10, 20):
            for obs in sorted(early.index):
                e, l = early.loc[obs].to_dict(), late.loc[obs].to_dict()
                es, ls = state(e, lev), state(l, lev)
                for policy in POLICIES:
                    if policy == "early_2r":
                        branch, reason = (("early", "early_order") if es == "entered" else
                                          ("no_order", "early_rejected") if es == "rejected" else ("unknown", "early_source_unknown"))
                    elif policy == "late_2r":
                        branch, reason = (("late", "late_order") if ls == "entered" else
                                          ("no_order", "late_rejected") if ls == "rejected" else ("unknown", "late_source_unknown"))
                    else:
                        branch, reason = stage_branch(es, ls, e.get("entry_exec_ts"), l.get("entry_exec_ts"))
                    row = {"year": year, "leverage": lev, "observation_id": obs, "policy": policy,
                           "early_status": e["status"], "early_state": es, "early_ref_ts": e.get("entry_exec_ts"),
                           "late_status": l["status"], "late_state": ls, "late_ref_ts": l.get("entry_exec_ts"),
                           "branch": branch, "reason": reason, "one_imbalance": e.get("one_imbalance"),
                           "target_r": "", "status": "unknown" if branch == "unknown" else "no_order",
                           "entry_ts": "", "entry_fill": "", "exit_ts": "", "exit_raw": "", "side": "", "funding": "",
                           "net_base": "", "net_s075": "", "net_s100": ""}
                    if branch in ("early", "late"):
                        target = choose_target(policy, branch, e.get("one_imbalance"))
                        row["target_r"] = target
                        key = (obs, f"one_observation_{target}r_{lev}x" if branch == "early" else f"normal_2r_{lev}x")
                        path = (alt_map if target == 1 else early_map if branch == "early" else late_map).get(key)
                        if not path or path.get("status") != "verified" or path.get("risk_status") != "verified" or pd.isna(path.get("liq_proxy")) or bool(path["liq_proxy"]):
                            row.update(status="unknown", reason="entered_path_or_risk_unknown")
                        else:
                            if target == 1:
                                baseline = early_map[(obs, f"one_observation_2r_{lev}x")]
                                for field in ("entry_ts", "side"):
                                    assert path[field] == baseline[field]
                                for field in ("entry_fill", "initial_stop"):
                                    assert abs(Decimal(str(path[field])) - Decimal(str(baseline[field]))) < Decimal("1e-9")
                            ref_ts = int(e["entry_exec_ts"] if branch == "early" else l["entry_exec_ts"])
                            assert int(path["entry_signal_reference_ts"]) == ref_ts
                            assert int(path["entry_ts"]) >= ref_ts + (1000 if branch == "early" else 5000)
                            assert int(path["exit_ts"]) >= int(path["exit_signal_ts"]) + 5000
                            assert abs(net_value(path, Decimal("0.0005")) - Decimal(str(path["net_per_unit_notional"]))) < Decimal("1e-11")
                            row.update(status="trade", **{k: path[k] for k in ("entry_ts", "entry_fill", "exit_ts", "exit_raw", "side", "funding")})
                            for name, slip in SLIPS:
                                row[name] = str(net_value(path, slip))
                    rows.append(row)
            for policy in POLICIES:
                cohort = [r for r in rows if r["year"] == year and r["leverage"] == lev and r["policy"] == policy]
                assert len(cohort) == len(early)
                for col, slip in SLIPS:
                    summary.append({"year": year, "leverage": lev, "policy": policy,
                                    "exit_slippage_pct": float(slip * 100), **summarize(cohort, col)})
            refrow = next(x for x in ref["rows"] if x["leverage"] == lev)
            for policy, key in (("early_2r", "one_second_observation"), ("late_2r", "five_second_observation_baseline")):
                actual = next(x for x in summary if x["year"] == year and x["leverage"] == lev and x["policy"] == policy and x["exit_slippage_pct"] == .05)
                expected = refrow[key]
                assert (actual["trades"], actual["wins"], actual["unknown"]) == (expected["trades"], expected["wins"], expected["unknown"])
                assert abs(actual["mean_net_pct_notional"] - expected["mean_net_pct_notional"]) < 1e-10
    detail = H / "分层入场逐候选明细.csv"
    with detail.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out = {"rows": summary, "detail_sha256": sha(detail), "plan_sha256": sha(H / "研究方案.md"),
           "code_sha256": sha(Path(__file__)), "input_sha256": provenance,
           "note": "Retrospective unit paths; no account simulation. Unknowns and delayed decisions remain unresolved."}
    (H / "分层入场单位结果.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for x in summary:
        if x["leverage"] == 20 and x["exit_slippage_pct"] == .05:
            print(json.dumps(x, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
