"""Independently replay all known-path wallet events and planned risk limits."""
from __future__ import annotations

import csv
from decimal import Decimal as D, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R106 = P / "第一百零六轮_一秒五秒分层入场"
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
spec = importlib.util.spec_from_file_location("ext98_wallet_audit_108", R98 / "run_wallet.py")
old_wallet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old_wallet)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def near(a, b):
    return abs(D(str(a)) - D(str(b))) < D("1e-8")


def main():
    bulk.runner.guard(start=True)
    result_file = H / "共享钱包情景结果.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    expected_files = {"inputs_sha256": "钱包已知输入.json", "outcomes_sha256": "共享钱包逐笔.csv",
                      "journal_sha256": "共享钱包事件.csv", "unit_result_sha256": "跟踪退出配对结果.json",
                      "unit_audit_sha256": "跟踪退出汇总独立核验.json", "plan_sha256": "共享钱包研究方案.md",
                      "code_sha256": "run_wallet.py"}
    for key, name in expected_files.items():
        assert result[key] == sha(H / name), name
    unit_audit = json.loads((H / "跟踪退出汇总独立核验.json").read_text(encoding="utf-8"))
    assert unit_audit["all_checks_pass"] and unit_audit["summary_sha256"] == result["unit_result_sha256"]
    assert result["original_wallet_audit_sha256"] == sha(R98 / "共享钱包独立核验.json")
    original_audit = json.loads((R98 / "共享钱包独立核验.json").read_text(encoding="utf-8"))
    assert original_audit["all_checks_pass"] and original_audit["result_sha256"] == sha(R98 / "共享钱包情景汇总.json")
    assert result["engine_sha256"] == sha(R106 / "wallet_engine_param.py")
    synthetic = json.loads((R106 / "钱包参数合成核验.json").read_text(encoding="utf-8"))
    assert synthetic["all_checks_pass"] and synthetic["engine_sha256"] == result["engine_sha256"]
    assert synthetic["test_code_sha256"] == sha(R106 / "test_wallet_param.py")
    assert result["engine_test_sha256"] == sha(R106 / "钱包参数合成核验.json")
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    for filename, digest in frozen["files"].items():
        assert sha(Path(filename)) == digest
    inputs = json.loads((H / "钱包已知输入.json").read_text(encoding="utf-8"))
    previous = {(r["observation_id"], r["leverage"]): r for r in old_wallet.load_records()}
    alternate = pd.read_parquet(H / "跟踪退出单位账本.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    with (H / "跟踪退出配对明细.csv").open(encoding="utf-8", newline="") as f:
        unit_rows = list(csv.DictReader(f))
    with (H / "共享钱包逐笔.csv").open(encoding="utf-8", newline="") as f:
        outcomes = list(csv.DictReader(f))
    with (H / "共享钱包事件.csv").open(encoding="utf-8", newline="") as f:
        events = list(csv.DictReader(f))
    assert len(result["rows"]) == 16 and len(inputs) == 4
    indexed_inputs = {(x["leverage"], x["cohort"]): x["records"] for x in inputs}
    units = {(int(r["leverage"]), r["observation_id"]): r for r in unit_rows}
    path_count = 0
    for (lev, cohort), records in indexed_inputs.items():
        expected_ids = {key[1] for key in units if key[0] == lev}
        assert {r["observation_id"] for r in records} == expected_ids
        for r in records:
            obs = r["observation_id"]
            u = units[(lev, obs)]
            orig = previous[(obs, lev)]
            for key in ("side", "decision_ts", "reference_ts", "reference", "stop", "entry_ts", "entry_fill"):
                assert str(r[key]) == str(orig[key])
            selected_alt = cohort == "trailing"
            if selected_alt:
                path = alternate[(obs, orig["variant"])]
                assert path["risk_status"] == "verified" and not bool(path["liq_proxy"])
                assert int(r["exit_signal_ts"]) == int(path["exit_signal_ts"]) and int(r["exit_ts"]) == int(path["exit_ts"])
                assert near(r["exit_fill"], path["exit_fill"]) and r["funding_events"] == json.loads(path["funding_events_json"])
            else:
                for key in ("exit_signal_ts", "exit_ts", "exit_fill", "unit_net", "funding_events"):
                    assert r[key] == orig[key]
            field = {"baseline_paired": "original_net", "trailing": "trailing_net"}[cohort]
            assert int(r["entry_ts"]) == int(u["entry_ts"]) and near(r["unit_net"], u[field])
            path_count += 1

    event_count = position_count = 0
    with localcontext() as ctx:
        ctx.prec = 42
        for summary in result["rows"]:
            lev, cohort = summary["leverage"], summary["cohort"]
            label, reverse = summary["risk_label"], summary["reverse_ties"]
            per_trade, total_risk = D(summary["per_trade_fraction"]), D(summary["total_risk_fraction"])
            assert (per_trade, total_risk) in ((D(".005"), D(".01")), (D(".0025"), D(".005")))
            records = indexed_inputs[(lev, cohort)]
            def matching(row):
                return (int(row["leverage"]) == lev and row["cohort"] == cohort
                        and row["risk_label"] == label and row["reverse_ties"] == str(reverse))
            actual = {r["observation_id"]: r for r in outcomes if matching(r)}
            journal = [r for r in events if matching(r)]
            assert len(actual) == len(records) == summary["known_opportunities"]
            rank = {obs: i for i, obs in enumerate(sorted((r["observation_id"] for r in records), reverse=reverse))}
            schedule = []
            for r in records:
                obs = r["observation_id"]
                assert r["reference_ts"] >= r["decision_ts"] + 1000
                assert r["entry_ts"] >= r["reference_ts"] + 1000
                assert r["exit_ts"] >= r["exit_signal_ts"] + 5000
                schedule.extend([(r["reference_ts"], 0, rank[obs], 0, "reference", r, None),
                                 (r["entry_ts"], 1, rank[obs], 0, "entry", r, None),
                                 (r["exit_ts"], 3, rank[obs], 0, "exit", r, None)])
                for i, f in enumerate(r["funding_events"]):
                    assert r["entry_ts"] <= f["settlement_ts"] <= r["exit_ts"]
                    schedule.append((f["settlement_ts"], 2, rank[obs], i, "funding", r, f))
            schedule.sort(key=lambda e: e[:4])
            wallet, locked, peak, dd = D(1000), D(0), D(1000), D(0)
            pending, active, closed = {}, {}, []
            maximum_active = 0
            journal_index = 0

            def snapshot(ts, kind, obs, status):
                nonlocal peak, dd, maximum_active, journal_index, event_count
                peak = max(peak, wallet)
                dd = max(dd, (peak - wallet) / peak)
                maximum_active = max(maximum_active, len(active))
                actual_event = journal[journal_index]
                journal_index += 1
                event_count += 1
                assert (int(actual_event["ts"]), actual_event["event"], actual_event["observation_id"], actual_event["status"]) == (ts, kind, obs, status)
                assert near(actual_event["wallet"], wallet) and near(actual_event["locked_margin"], locked)
                assert near(actual_event["pending_reserve"], sum((v["reserve"] for v in pending.values()), D(0)))
                assert near(actual_event["planned_open_risk"], sum((v["risk"] for v in [*pending.values(), *active.values()]), D(0)))

            for ts, _, _, _, kind, r, funding in schedule:
                obs, o = r["observation_id"], actual[r["observation_id"]]
                if kind == "reference":
                    side, ref, stop = D(r["side"]), D(r["reference"]), D(r["stop"])
                    estimated = ref * (1 + side * D(".0005"))
                    estimated_exit = stop * (1 - side * D(".0005"))
                    loss_unit = side * (estimated - estimated_exit) + D(".0005") * (estimated + estimated_exit)
                    assert loss_unit > 0
                    reserve = sum((v["reserve"] for v in pending.values()), D(0))
                    used = sum((v["risk"] for v in [*pending.values(), *active.values()]), D(0))
                    free = max(D(0), wallet - locked - reserve)
                    budget = max(D(0), min(wallet * per_trade, wallet * total_risk - used))
                    margin_unit = estimated / D(lev) + D(".0005") * estimated
                    qty = D(0) if budget <= abs(wallet) * D("1e-18") or free <= abs(wallet) * D("1e-18") else min(budget / loss_unit, free / margin_unit)
                    if qty <= 0:
                        assert o["status"] == "signal_rejected_budget_or_funds" and near(o["net_pnl"], 0)
                        snapshot(ts, kind, obs, "signal_rejected_budget_or_funds")
                        continue
                    pending[obs] = {"qty": qty, "reserve": qty * margin_unit, "risk": qty * loss_unit,
                                    "reference_wallet": wallet, "estimated": estimated}
                    assert near(o["quantity"], qty) and near(o["planned_risk"], qty * loss_unit)
                    assert near(o["reference_wallet"], wallet) and near(o["estimated_entry"], estimated)
                    snapshot(ts, kind, obs, "reserved")
                elif kind == "entry":
                    if obs not in pending:
                        continue
                    order = pending.pop(obs)
                    margin = order["qty"] * D(r["entry_fill"]) / D(lev)
                    fee = order["qty"] * D(r["entry_fill"]) * D(".0005")
                    free = wallet - locked - sum((v["reserve"] for v in pending.values()), D(0))
                    if margin + fee > free + D("1e-25"):
                        assert o["status"] == "entry_rejected_insufficient_margin" and near(o["net_pnl"], 0)
                        snapshot(ts, kind, obs, "entry_rejected_insufficient_margin")
                        continue
                    wallet -= fee
                    locked += margin
                    active[obs] = {**order, "margin": margin, "fee": fee, "funding": D(0)}
                    assert near(o["margin"], margin) and near(o["open_fee"], fee)
                    snapshot(ts, kind, obs, "filled")
                elif kind == "funding":
                    if obs not in active:
                        continue
                    charge = D(str(funding["charge"])) * active[obs]["qty"] * D(r["entry_fill"])
                    wallet -= charge
                    active[obs]["funding"] += charge
                    snapshot(ts, kind, obs, "funding_applied")
                else:
                    if obs not in active:
                        continue
                    pos = active.pop(obs)
                    exit_ = D(r["exit_fill"])
                    closing = pos["qty"] * (D(r["side"]) * (exit_ - D(r["entry_fill"])) - exit_ * D(".0005"))
                    wallet += closing
                    locked -= pos["margin"]
                    pnl = closing - pos["fee"] - pos["funding"]
                    assert o["status"] == "closed" and near(o["net_pnl"], pnl)
                    assert near(pnl, pos["qty"] * D(r["entry_fill"]) * D(r["unit_net"]))
                    assert near(o["funding_paid"], pos["funding"])
                    closed.append((pnl, pos["reference_wallet"]))
                    position_count += 1
                    snapshot(ts, kind, obs, "closed")
            assert journal_index == len(journal) and not pending and not active and near(locked, 0)
            pnl_values = [v[0] for v in closed]
            assert near(wallet, summary["final_wallet"]) and near(wallet - D(1000), summary["net_pnl"])
            assert near((wallet / D(1000) - 1) * 100, summary["net_return_pct"])
            assert near(dd * 100, summary["realized_wallet_drawdown_pct"])
            assert len(closed) == summary["simulated_trades"] and sum(x > 0 for x in pnl_values) == summary["net_wins"]
            if pnl_values:
                assert near(D(100) * sum(x > 0 for x in pnl_values) / len(pnl_values), summary["net_win_rate_pct"])
                positive = sum((x for x in pnl_values if x > 0), D(0))
                negative = -sum((x for x in pnl_values if x < 0), D(0))
                if negative:
                    assert near(positive / negative, summary["profit_factor"])
                else:
                    assert summary["profit_factor"] is None
            assert len(records) - len(closed) == summary["rejected_signals"] and maximum_active == summary["maximum_open_positions"]
            assert sum(-pnl > ref * per_trade for pnl, ref in closed) == summary["planned_loss_exceeded_count"]
            worst = max((-pnl / ref * 100 for pnl, ref in closed if pnl < 0), default=D(0))
            assert near(worst, summary["worst_loss_pct_reference_wallet"])
    output = {"all_checks_pass": True, "scenarios_checked": len(result["rows"]),
              "input_paths_checked": path_count, "wallet_events_checked": event_count, "closed_paths_checked": position_count,
              "result_sha256": sha(result_file), "audit_code_sha256": sha(Path(__file__)),
              "note": "Cash events and plan risk independently reconstructed; floating equity and unknowns remain excluded."}
    (H / "共享钱包独立核验.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
