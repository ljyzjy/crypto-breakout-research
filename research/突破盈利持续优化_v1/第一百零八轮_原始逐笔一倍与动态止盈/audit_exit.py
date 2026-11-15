"""Independent timestamp parser and scalar risk audit, resumable per source day."""
from decimal import Decimal as D
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R100 = P / "第一百轮_突破无进展提前退出"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(bulk.R93))
import audit_raw_samples
sys.path.insert(0, str(R100))
spec = importlib.util.spec_from_file_location("ext100_audit", R100 / "audit_exit.py")
previous_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous_audit)


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def evaluate(path, seq):
    start, end = int(path["entry_ts"]), int(path["exit_signal_ts"])
    if end <= start:
        return "original", "original_signal_first", None, None
    side, entry, risk = int(path["side"]), D(str(path["entry_fill"])), D(str(path["actual_entry_risk"]))
    if side not in (-1, 1) or entry <= 0 or risk <= 0:
        return "unknown", "invalid_actual_risk", None, None
    first = next((x for x in seq if x[0] >= start), None)
    if first is None or first[0] != start:
        return "unknown", "missing_entry_reference", None, None
    if abs(first[2] - D(str(path["entry_raw"]))) > D("1e-9"):
        return "unknown", "entry_reference_mismatch", None, None
    orig_fill = next((x for x in seq if x[0] >= int(path["exit_ts"])), None)
    if (orig_fill is None or orig_fill[0] != int(path["exit_ts"])
            or abs(orig_fill[2] - D(str(path["exit_raw"]))) > D("1e-9")):
        return "unknown", "original_exit_reference_mismatch", None, None
    target = next((x for x in seq if start <= x[0] < end and D(side) * (x[2] - entry) >= risk), None)
    if target is None:
        return "original", "one_r_not_before_original", None, None
    fill = next((x for x in seq if x[0] >= target[0] + 5000), None)
    if fill is None:
        return "unknown", "missing_delayed_exit", target, None
    if fill[2] <= 0:
        return "unknown", "invalid_exit_price", target, fill
    return "one_r_exit", "one_r_target", target, fill


def main():
    bulk.runner.guard(start=True)
    meta = json.loads((H / "一倍止盈回放质量.json").read_text(encoding="utf-8"))
    assert meta["code_sha256"] == bulk.sha(H / "run_raw_1r.py")
    assert meta["ledger_sha256"] == bulk.sha(H / "一倍止盈单位账本.parquet")
    assert meta["frozen_sha256"] == bulk.sha(H / "输入冻结.json")
    got = pd.read_parquet(H / "一倍止盈单位账本.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    baseline = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").set_index(["observation_id", "variant"]).to_dict("index")
    log = {(x["observation_id"], x["variant"]): x for x in meta["cases"]}
    assert len(got) == len(log) == meta["candidate_paths"] == 261
    byobs = {}
    for obs, var in got:
        byobs.setdefault(obs, []).append(var)
    candidates = pd.read_parquet(bulk.R90 / "候选数据/固定十一币双币过滤潜在触价.parquet")
    marks, funds, statuses = previous_audit.risk_inputs()
    fingerprint = hashlib.sha256((bulk.sha(H / "一倍止盈回放质量.json") + bulk.sha(Path(__file__))).encode()).hexdigest()
    dest = bulk.runner.ROOT / "one_r_raw_2022_audit_checkpoints"
    assert dest.resolve().is_relative_to(bulk.runner.ROOT.resolve())
    dest.mkdir(parents=True, exist_ok=True)
    checked = settled = 0
    for (sym, day), g in candidates.groupby(["contract", "day"], sort=True):
        if not set(g.observation_id).intersection(byobs):
            continue
        bulk.runner.guard()
        events = g.to_dict("records")
        token = hashlib.sha256((fingerprint + "|" + str(sym) + "|" + str(day)).encode()).hexdigest()
        checkpoint = dest / (token + ".json")
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            assert saved["fingerprint"] == fingerprint and saved["symbol"] == sym and saved["day"] == str(day)
            checked += saved["checked"]
            settled += saved["settled"]
            print("EXT108_AUDIT", checked, "/", len(got), sym, day, "cached", flush=True)
            continue
        cp_path = bulk.runner.ROOT / "raw_2022_full_checkpoints" / (bulk.runner.key(bulk.fingerprint(), sym, day, events) + ".json")
        cp = json.loads(cp_path.read_text(encoding="utf-8"))
        assert cp["fingerprint"] == bulk.fingerprint()
        arcs = [a for a in cp["archives"] if a["kind"] == "trades"]
        paths = [baseline[(e["observation_id"], v)] for e in events for v in byobs.get(e["observation_id"], [])]
        needed = [r for r in paths if int(r["exit_signal_ts"]) > int(r["entry_ts"])]
        seq = []
        if needed:
            lo, hi = min(int(r["entry_ts"]) for r in needed), max(int(r["exit_ts"]) for r in needed) + 1
            for a in arcs:
                assert bulk.sha(a["path"]) == a["sha256"]
                seq.extend(audit_raw_samples.independent_window(a["path"], "trades", lo, hi))
            seq.sort(key=lambda x: (x[0], x[1]))
        count = settled_group = 0
        for e in events:
            obs = e["observation_id"]
            for var in byobs.get(obs, []):
                original, new, want = baseline[(obs, var)], got[(obs, var)], log[(obs, var)]
                action, reason, target, fill = evaluate(original, seq)
                assert (want["action"], want["reason"]) == (action, reason) and new["one_r_action"] == action
                if action == "one_r_exit":
                    assert int(new["exit_signal_ts"]) == target[0] and int(new["exit_ts"]) == fill[0]
                    assert near(new["exit_raw"], fill[2]) and near(new["exit_fill"], fill[2] * (1 - D(int(original["side"])) * D(".0005")))
                    assert int(new["exit_ts"]) <= int(original["exit_ts"])
                elif action == "original":
                    for name in ("entry_ts", "exit_signal_ts", "exit_ts"):
                        assert int(new[name]) == int(original[name])
                    for name in ("entry_fill", "exit_raw", "exit_fill", "net_per_unit_notional"):
                        assert near(new[name], original[name])
                else:
                    assert new["risk_status"] == "one_r_path_unknown"
                if new["risk_status"] == "verified":
                    previous_audit.audit_risk({**new, "observation_id": obs, "variant": var}, marks, funds, statuses)
                    settled_group += 1
                count += 1
        saved = {"fingerprint": fingerprint, "symbol": sym, "day": str(day), "checked": count, "settled": settled_group,
                 "source_checkpoint_sha256": bulk.sha(cp_path)}
        tmp = checkpoint.with_suffix(".partial")
        bulk.runner.guard()
        tmp.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        tmp.replace(checkpoint)
        checked += count
        settled += settled_group
        print("EXT108_AUDIT", checked, "/", len(got), sym, day, "verified", flush=True)
    assert checked == len(got)
    out = {"all_checks_pass": True, "paths_checked": checked, "risk_settlements_checked": settled,
           "source_sha256": bulk.sha(H / "一倍止盈回放质量.json"), "ledger_sha256": bulk.sha(H / "一倍止盈单位账本.parquet"),
           "code_sha256": bulk.sha(Path(__file__)), "note": "Independent chunk parser and scalar mark/funding checks; source caches remain proxies."}
    (H / "一倍止盈逐笔独立核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT108_AUDIT_PASS", checked, settled, flush=True)


if __name__ == "__main__":
    main()
