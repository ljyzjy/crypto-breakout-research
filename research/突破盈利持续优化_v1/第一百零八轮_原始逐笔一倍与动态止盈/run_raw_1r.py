"""Resumable 2022 raw-trade 1R paths; preserves the original resource guards."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R100 = P / "第一百轮_突破无进展提前退出"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(R100))
import run_exit as previous
spec = importlib.util.spec_from_file_location("ext108_exit_1r", H / "exit_1r.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
apply = engine.apply


def check_frozen():
    f = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert f["freeze_code_sha256"] == bulk.sha(H / "freeze_inputs.py")
    for path, digest in f["files"].items():
        assert bulk.sha(path) == digest
    assert bulk.frozen()
    return f


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return clean(value.item())
    return value


def main():
    bulk.runner.guard(start=True)
    check_frozen()
    fprint = hashlib.sha256((bulk.sha(H / "输入冻结.json") + bulk.sha(Path(__file__))).encode()).hexdigest()
    dest = bulk.runner.ROOT / "one_r_raw_2022_checkpoints"
    assert dest.resolve().is_relative_to(bulk.runner.ROOT.resolve())
    dest.mkdir(parents=True, exist_ok=True)
    detail = pd.read_csv(R98 / "候选状态与单位账本.csv", dtype=str, keep_default_na=False)
    eligible = {(r["observation_id"], int(r["leverage"])) for r in detail.to_dict("records") if r["category"] == "trade"}
    ledger = pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet")
    candidates = pd.read_parquet(bulk.R90 / "候选数据/固定十一币双币过滤潜在触价.parquet")
    grouped = {}
    for row in ledger.to_dict("records"):
        lev = int(row["variant"].rsplit("_", 1)[1].rstrip("x"))
        if (row["observation_id"], lev) in eligible:
            grouped.setdefault(row["observation_id"], []).append(row)
    assert sum(map(len, grouped.values())) == len(eligible) == 261
    marks, funds, statuses = previous.risk_inputs()
    env, _ = previous.risk.risk_namespace()
    all_rows, all_cases = [], []
    for (sym, day), group in candidates.groupby(["contract", "day"], sort=True):
        events = group.to_dict("records")
        if not set(group.observation_id).intersection(grouped):
            continue
        bulk.runner.guard()
        key = hashlib.sha256((fprint + "|" + str(sym) + "|" + str(day)).encode()).hexdigest()
        checkpoint = dest / (key + ".json")
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            assert saved["fingerprint"] == fprint and saved["symbol"] == sym and saved["day"] == str(day)
            all_rows.extend(saved["rows"])
            all_cases.extend(saved["cases"])
            print("EXT108_GROUP", len(all_cases), "/", len(eligible), sym, day, "cached", flush=True)
            continue
        source_cp = bulk.runner.ROOT / "raw_2022_full_checkpoints" / (bulk.runner.key(bulk.fingerprint(), sym, day, events) + ".json")
        cp = json.loads(source_cp.read_text(encoding="utf-8"))
        assert cp["fingerprint"] == bulk.fingerprint() and cp["status"] == "verified"
        archives = [a for a in cp["archives"] if a["kind"] == "trades"]
        paths = [r for e in events for r in grouped.get(e["observation_id"], [])]
        needs = [r for r in paths if int(r["exit_signal_ts"]) > int(r["entry_ts"])]
        prices = []
        if needs:
            for a in archives:
                assert bulk.sha(a["path"]) == a["sha256"]
            lo, hi = min(int(r["entry_ts"]) for r in needs), max(int(r["exit_ts"]) for r in needs) + 1
            source = []
            for a in archives:
                bulk.runner.guard()
                source.extend(previous.raw.read_window(a["path"], "trades", lo, hi))
            source.sort(key=lambda x: (x[0], x[1]))
            prices = [(r[0], r[2]) for r in source]
        rows, cases = [], []
        for row in paths:
            action = apply(row, prices)
            new = dict(row)
            if action["action"] == "one_r_exit":
                for name in ("exit_signal_ts", "exit_ts", "exit_raw", "exit_fill"):
                    new[name] = action[name]
                new["reason"] = "one_r_target"
                new.update(env["settle"](SimpleNamespace(**new), marks, funds, statuses))
            elif action["action"] == "unknown":
                new.update(risk_status="one_r_path_unknown", liq_proxy=None, funding=None,
                           funding_events_json=None, entry_fee=None, exit_fee=None,
                           net_per_unit_notional=None, net_pct_notional=None)
            new["baseline_net_per_unit_notional"] = row["net_per_unit_notional"]
            new["baseline_exit_ts"] = row["exit_ts"]
            new["one_r_action"] = action["action"]
            new["one_r_reason"] = action["reason"]
            rows.append(clean(new))
            cases.append(clean({"observation_id": row["observation_id"], "variant": row["variant"], **action}))
        saved = {"fingerprint": fprint, "symbol": sym, "day": str(day), "source_checkpoint_sha256": bulk.sha(source_cp),
                 "rows": rows, "cases": cases}
        tmp = checkpoint.with_suffix(".partial")
        bulk.runner.guard()
        tmp.write_text(json.dumps(saved, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        tmp.replace(checkpoint)
        all_rows.extend(rows)
        all_cases.extend(cases)
        print("EXT108_GROUP", len(all_cases), "/", len(eligible), sym, day, "verified", flush=True)
    assert len(all_rows) == len(all_cases) == len(eligible)
    output = pd.DataFrame(all_rows)
    assert not output.duplicated(["observation_id", "variant"]).any()
    output.to_parquet(H / "一倍止盈单位账本.parquet", index=False)
    quality = {"candidate_paths": len(output), "actions": output.one_r_action.value_counts().to_dict(),
               "risk_statuses": output.risk_status.value_counts().to_dict(), "cases": all_cases,
               "ledger_sha256": bulk.sha(H / "一倍止盈单位账本.parquet"), "fingerprint": fprint,
               "frozen_sha256": bulk.sha(H / "输入冻结.json"), "code_sha256": bulk.sha(Path(__file__)),
               "note": "Checkpointed raw replay only; independent sample, aggregate and wallet audits still required."}
    (H / "一倍止盈回放质量.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("EXT108_REPLAY_COMPLETE", len(output), quality["actions"], flush=True)


if __name__ == "__main__":
    main()
