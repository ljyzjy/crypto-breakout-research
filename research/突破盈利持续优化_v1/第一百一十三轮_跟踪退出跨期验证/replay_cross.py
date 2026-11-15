"""Re-stream checksum-verified aggregate trades for fixed trailing exits."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import psutil

H = Path(__file__).resolve().parent
P = H.parent
R70 = P / "第七十轮_一秒观察一倍止盈"
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R112 = P / "第一百一十二轮_突破后跟踪退出"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(R70))
import replay_1r as previous
spec = importlib.util.spec_from_file_location("ext113_trailing", R112 / "trailing.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def frozen(year):
    data = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert data["code_sha256"] == bulk.sha(H / "freeze_cross.py")
    for path, sha in data["sources"].items():
        assert bulk.sha(path) == sha, path
    tasks, fp, count, snapshot = previous.prepare(year)
    ref = data["years"][year]
    assert (fp, count, snapshot, len(tasks)) == (ref["prior_fingerprint"], ref["paths"], ref["source_snapshot_sha256"], ref["task_groups"])
    return tasks, ref


def identity(year):
    return hashlib.sha256((year + "|" + bulk.sha(H / "输入冻结.json") + "|" + bulk.sha(Path(__file__))).encode()).hexdigest()


def cp_path(year, fingerprint, task):
    folder = bulk.runner.ROOT / f"trailing_cross_{year}_checkpoints"
    assert folder.resolve().is_relative_to(bulk.runner.ROOT.resolve())
    folder.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256((fingerprint + "|" + task["checkpoint"]).encode()).hexdigest()
    return folder / (token + ".json")


def run_task(year, task, fingerprint):
    target = cp_path(year, fingerprint, task)
    if target.exists():
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["fingerprint"] == fingerprint and saved["source_checkpoint"] == task["checkpoint"] and saved["status"] == "verified"
        return saved
    bulk.runner.guard()
    blocks = {e["observation_id"]: [] for e in task["events"]}
    windows = {e["observation_id"]: (e["trigger_minute"], e["quarter_end"] + 60000) for e in task["events"]}
    archives = []
    previous.public_range.WORKERS = 2
    for expected in task["archives"]:
        bulk.runner.guard()
        previous.public_range.MAX_BUFFER = 50_000_000 if psutil.virtual_memory().available >= 1536 * 1024 ** 2 else 0
        got, meta = previous.public_range.fetch(task["contract"], expected["day"], windows, bulk.runner.guard)
        assert meta["sha256"] == expected["sha256"] and meta["bytes"] == expected["bytes"]
        archives.append(meta)
        for obs in blocks:
            blocks[obs].extend(got[obs])
    rows = []
    for event in task["events"]:
        obs = event["observation_id"]
        if not blocks[obs]:
            rows.append({"observation_id": obs, "status": "missing_event_tape", "paths": {}})
            continue
        tape = pd.concat(blocks[obs], ignore_index=True).sort_values(["transact_time", "agg_trade_id"], kind="mergesort")
        prices = list(zip(tape.transact_time.astype("int64"), tape.price.astype(float)))
        reference = next((r for r in prices if r[0] >= event["entry_exec_ts"]), None)
        assert reference and reference[0] == event["entry_exec_ts"] and abs(reference[1] - event["raw_entry_1s"]) < 1e-9
        paths = {}
        for variant, old in event["old_paths"].items():
            path = {**old, "side": int(event["side"])}
            action = engine.apply(path, prices)
            new = dict(path)
            if action["action"] == "trailing_exit":
                for field in ("exit_signal_ts", "exit_ts", "exit_raw", "exit_fill"):
                    new[field] = action[field]
                new["reason"] = "activated_giveback"
            elif action["action"] == "unknown":
                new["status"] = "trailing_path_unknown"
            new["trailing_action"] = action["action"]
            new["trailing_reason"] = action["reason"]
            paths[variant] = new
        rows.append({"observation_id": obs, "status": "processed", "paths": paths})
    saved = {"fingerprint": fingerprint, "source_checkpoint": task["checkpoint"], "contract": task["contract"],
             "day": task["day"], "status": "verified", "archives": archives, "rows": rows}
    bulk.runner.guard()
    tmp = target.with_suffix(".partial")
    tmp.write_text(json.dumps(saved, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    tmp.replace(target)
    return saved


def main(year):
    bulk.runner.guard(start=True)
    tasks, ref = frozen(year)
    fp = identity(year)
    errors, done = [], 0
    for task in tasks:
        try:
            bulk.runner.guard()
            run_task(year, task, fp)
            done += 1
            print("EXT113_GROUP", year, done, "/", len(tasks), task["contract"], task["day"], flush=True)
        except Exception as exc:
            error = type(exc).__name__ + ":" + str(exc)[:180]
            errors.append({"checkpoint": task["checkpoint"], "error": error})
            print("EXT113_ERROR", year, task["contract"], task["day"], error, flush=True)
            if "headroom" in error or "disk_reserve" in error:
                break
    progress = {"year": year, "done": done, "groups": len(tasks), "eligible_paths": ref["paths"], "errors": errors,
                "fingerprint": fp, "code_sha256": bulk.sha(Path(__file__)), "frozen_sha256": bulk.sha(H / "输入冻结.json")}
    (H / f"{year}跟踪逐笔回放进度.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT113_REPLAY_STOP", json.dumps(progress, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] in ("2024", "2026")
    main(sys.argv[1])
