"""Fetch only six frozen pilot trade archives, with existing official-SHA safeguards."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

H = Path(__file__).resolve().parent
R104 = H.parent / "第一百零四轮_同秒成交加速门"
spec = importlib.util.spec_from_file_location("ext104_count_archive_109", R104 / "count_same_phase.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


def main():
    source.bulk.runner.guard(start=True)
    frozen = json.loads((H / "三日试点冻结.json").read_text(encoding="utf-8"))
    assert frozen["code_sha256"] == source.bulk.sha(H / "freeze_pilot.py")
    for name, digest in frozen["files"].items():
        assert source.bulk.sha(H / name) == digest
    records = []
    for day in frozen["days"]:
        for symbol in ("BTCUSDT", "ETHUSDT"):
            source.bulk.runner.guard()
            try:
                path, meta = source.archive(symbol, day)
                records.append({"symbol": symbol, **meta, "status": "verified"})
                print("EXT109_ARCHIVE", len(records), "/6", symbol, day, path.stat().st_size, flush=True)
            except Exception as exc:
                if "headroom" in str(exc):
                    raise
                records.append({"symbol": symbol, "day": day, "status": "unknown_source", "error": type(exc).__name__ + ":" + str(exc)[:160]})
                print("EXT109_ARCHIVE", len(records), "/6", symbol, day, "unknown_source", flush=True)
            progress = {"archives": records, "frozen_sha256": source.bulk.sha(H / "三日试点冻结.json"),
                        "code_sha256": source.bulk.sha(Path(__file__)),
                        "archive_engine_sha256": source.bulk.sha(R104 / "count_same_phase.py"),
                        "note": "Official checksum verifies source archive, not trading or fill quality."}
            (H / "三日逐笔档来源.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT109_FETCH_COMPLETE", len(records), sum(r["status"] == "verified" for r in records), flush=True)


if __name__ == "__main__":
    main()
