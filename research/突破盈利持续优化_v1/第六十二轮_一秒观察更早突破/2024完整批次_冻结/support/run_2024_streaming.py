"""Resume original 2024 replay with tested sequential ZIP transport only."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import psutil
import run_observation as runner

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
TAPE = ROOT / "work/oneobs62_2024/tape"
JOURNAL = H / "2024低内存顺序读取运行记录.jsonl"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def append(row):
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    test_path = H / "2024低内存顺序读取核验.json"
    test = json.loads(test_path.read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["runner_fingerprint"] == runner.fingerprint("2024")
    assert test["plan_sha256"] == sha(H / "2024低内存读取方案.md") and test["test_sha256"] == sha(H / "test_2024_stream_reader.py")
    assert test["runner_sha256"] == sha(H / "run_observation.py")
    assert test["range_sha256"] == sha(H.parent / "第四十八轮_固定一倍风险止盈/public_range.py")
    assert test["stream_sha256"] == sha(H.parent / "第四十七轮_一次重新突破确认/public_tape_stream.py")
    if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 850 * 1024**2:
        raise RuntimeError("startup_headroom")
    TAPE.mkdir(parents=True, exist_ok=True)
    before = {p.name: sha(p) for p in TAPE.glob("*.json")}
    ident = {"started_utc": datetime.now(timezone.utc).isoformat(), "wrapper_sha256": sha(Path(__file__)), "test_sha256": sha(test_path), "runner_fingerprint": runner.fingerprint("2024"), "existing_checkpoints": before, "archive_transport": "sequential_sha256_verified", "original_guards_unchanged": True}
    append({"event": "start", **ident})
    runner.public_range.MAX_BUFFER = 0
    runner.public_range.WORKERS = 1
    try:
        runner.main("2024")
    finally:
        after = {p.name: sha(p) for p in TAPE.glob("*.json")}
        assert all(after.get(k) == v for k, v in before.items())
        append({"event": "end", "started_utc": ident["started_utc"], "ended_utc": datetime.now(timezone.utc).isoformat(), "new_checkpoints": {k: v for k, v in after.items() if k not in before}})


if __name__ == "__main__":
    main()
