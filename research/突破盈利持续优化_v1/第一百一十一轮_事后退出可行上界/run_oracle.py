"""Resumable future-aware exit bound, with funding-unknown paths excluded."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R100 = P / "第一百轮_突破无进展提前退出"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(R100))
import run_exit as previous
spec = importlib.util.spec_from_file_location("ext111_oracle", H / "oracle_exit.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def check_frozen():
    data = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert data["code_sha256"] == bulk.sha(H / "freeze_inputs.py")
    for path, digest in data["files"].items():
        assert bulk.sha(path) == digest, path
    bulk.frozen()


def funding_status(symbol, start, end, funds, statuses, funding_ok):
    month_rows = {}
    for t in range(start // 60000 * 60000, end // 60000 * 60000 + 60000, 60000):
        month = pd.Timestamp(t, unit="ms", tz="UTC").strftime("%Y-%m")
        if statuses.get(("fundingRate", symbol, month)) != "verified":
            return "unknown_funding_source"
        rows = funds.get((symbol, month), [])
        if not funding_ok(rows, t):
            return "unknown_funding_coverage"
        month_rows[month] = rows
    if any(start <= int(x["ts"]) <= end for rows in month_rows.values() for x in rows):
        return "unknown_funding_event"
    return "known"


def main():
    bulk.runner.guard(start=True)
    check_frozen()
    fp = hashlib.sha256((bulk.sha(H / "输入冻结.json") + bulk.sha(Path(__file__))).encode()).hexdigest()
    dest = bulk.runner.ROOT / "oracle_2022_exit_checkpoints"
    assert dest.resolve().is_relative_to(bulk.runner.ROOT.resolve())
    dest.mkdir(parents=True, exist_ok=True)
    detail = pd.read_csv(R98 / "候选状态与单位账本.csv", dtype=str, keep_default_na=False)
    eligible = {(x["observation_id"], int(x["leverage"])) for x in detail.to_dict("records") if x["category"] == "trade"}
    grouped = {}
    for row in pd.read_parquet(R98 / "原始逐笔批次/单位净收益与风险.parquet").to_dict("records"):
        lev = int(row["variant"].rsplit("_", 1)[1].rstrip("x"))
        if (row["observation_id"], lev) in eligible:
            grouped.setdefault(row["observation_id"], []).append(row)
    assert sum(map(len, grouped.values())) == len(eligible) == 261
    candidates = pd.read_parquet(bulk.R90 / "候选数据/固定十一币双币过滤潜在触价.parquet")
    _, funds, statuses = previous.risk_inputs()
    env, _ = previous.risk.risk_namespace()
    all_rows = []
    for (sym, day), group in candidates.groupby(["contract", "day"], sort=True):
        events = group.to_dict("records")
        if not set(group.observation_id).intersection(grouped):
            continue
        bulk.runner.guard()
        key = hashlib.sha256((fp + "|" + str(sym) + "|" + str(day)).encode()).hexdigest()
        checkpoint = dest / (key + ".json")
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            assert saved["fingerprint"] == fp and saved["symbol"] == sym and saved["day"] == str(day)
            all_rows.extend(saved["rows"])
            print("EXT111_GROUP", len(all_rows), "/", len(eligible), sym, day, "cached", flush=True)
            continue
        source_cp = bulk.runner.ROOT / "raw_2022_full_checkpoints" / (bulk.runner.key(bulk.fingerprint(), sym, day, events) + ".json")
        cp = json.loads(source_cp.read_text(encoding="utf-8"))
        assert cp["fingerprint"] == bulk.fingerprint() and cp["status"] == "verified"
        arcs = [a for a in cp["archives"] if a["kind"] == "trades"]
        for arc in arcs:
            assert bulk.sha(arc["path"]) == arc["sha256"]
        rows = []
        for event in events:
            paths = grouped.get(event["observation_id"], [])
            if not paths:
                continue
            lo = min(int(x["entry_ts"]) for x in paths)
            hi = max(int(x["quarter_end"]) for x in paths) + 60000
            source = []
            try:
                for arc in arcs:
                    bulk.runner.guard()
                    source.extend(previous.raw.read_window(arc["path"], "trades", lo, hi))
                source.sort(key=lambda x: (x[0], x[1]))
                ticks = [(x[0], x[2]) for x in source]
                error = None
            except (MemoryError, RuntimeError, ValueError) as exc:
                # Resource reserve violations must stop work; bounded or absent
                # market data remain unknown and never become losing trades.
                if "headroom" in str(exc) or "disk_reserve" in str(exc):
                    raise
                error = type(exc).__name__ + ":" + str(exc)[:160]
                ticks = []
            for row in paths:
                lev = int(row["variant"].rsplit("_", 1)[1].rstrip("x"))
                out = {"observation_id": row["observation_id"], "variant": row["variant"],
                       "leverage": lev, "contract": sym, "day": str(day),
                       "entry_ts": int(row["entry_ts"]), "quarter_end": int(row["quarter_end"]),
                       "baseline_net": str(row["net_per_unit_notional"])}
                result = {"status": "unknown_raw_window", "error": error} if error else engine.evaluate(row, ticks, int(row["quarter_end"]))
                if result["status"] == "known":
                    status = funding_status(sym, int(row["entry_ts"]), result["forced_exit_ts"], funds, statuses, env["funding_ok"])
                    if status == "known":
                        assert abs(float(row["funding"])) < 1e-12
                    else:
                        result = {"status": status, "deadline_ts": result["deadline_ts"], "forced_exit_ts": result["forced_exit_ts"]}
                out.update(result)
                rows.append(out)
            del source, ticks
        saved = {"fingerprint": fp, "symbol": sym, "day": str(day), "source_checkpoint_sha256": bulk.sha(source_cp), "rows": rows}
        tmp = checkpoint.with_suffix(".partial")
        bulk.runner.guard()
        tmp.write_text(json.dumps(saved, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        tmp.replace(checkpoint)
        all_rows.extend(rows)
        print("EXT111_GROUP", len(all_rows), "/", len(eligible), sym, day, "verified", flush=True)
    assert len(all_rows) == len(eligible)
    assert len({(r["observation_id"], r["variant"]) for r in all_rows}) == len(all_rows)
    output = {"fingerprint": fp, "frozen_sha256": bulk.sha(H / "输入冻结.json"), "code_sha256": bulk.sha(Path(__file__)),
              "rows": all_rows, "note": "Future-aware upper bound only; not an executable trading rule."}
    (H / "退出上界逐笔.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT111_REPLAY_COMPLETE", len(all_rows), flush=True)


if __name__ == "__main__":
    main()
