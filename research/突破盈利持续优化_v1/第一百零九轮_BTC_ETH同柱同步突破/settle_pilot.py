"""Apply official minute mark/funding proxies to frozen pilot paths."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(bulk.R90))
import settle_risk_2022 as risk
M = 60000


def main():
    bulk.runner.guard(start=True)
    paths_path = H / "三日逐笔路径.json"
    paths_doc = json.loads(paths_path.read_text(encoding="utf-8"))
    assert paths_doc["frozen_sha256"] == bulk.sha(H / "三日试点冻结.json")
    assert paths_doc["archive_source_sha256"] == bulk.sha(H / "三日逐笔档来源.json")
    assert paths_doc["engine_sha256"] == bulk.sha(H / "dual_pilot_engine.py")
    assert paths_doc["code_sha256"] == bulk.sha(H / "run_pilot_paths.py")
    assert risk.verify_header_compatibility()["all_checks_pass"]
    valid = [p for p in paths_doc["paths"] if p["status"] == "verified"]
    required = {}
    for p in valid:
        for ts in range(int(p["entry_ts"]) // M * M, int(p["exit_ts"]) // M * M + M, M):
            month = pd.Timestamp(ts, unit="ms", tz="UTC").strftime("%Y-%m")
            required.setdefault((p["contract"], month), set()).add(ts)
    specs = []
    for (symbol, month), times in sorted(required.items()):
        specs.extend([("markPriceKlines", symbol, month, sorted(times)), ("fundingRate", symbol, month, [])])
    env, engine_hash = risk.risk_namespace()
    cache = bulk.runner.ROOT / "dual_2022_pilot_risk"
    assert cache.resolve().is_relative_to(bulk.runner.ROOT.resolve())
    cache.mkdir(parents=True, exist_ok=True)
    env["WORK"] = cache
    env["MIN_FREE"] = 2_200_000_000
    fingerprint = hashlib.sha256((bulk.sha(H / "三日试点冻结.json") + bulk.sha(paths_path) + bulk.sha(Path(__file__)) + engine_hash).encode()).hexdigest()
    env["FINGERPRINT"] = fingerprint
    sources, marks, funds, statuses = [], {}, {}, {}
    for item in specs:
        bulk.runner.guard()
        kind, symbol, month, times = item
        r = env["task"](item)
        statuses[(kind, symbol, month)] = r["status"]
        if r["status"] == "verified":
            if kind == "markPriceKlines":
                for x in r["rows"]:
                    marks[(symbol, int(x["ts"]))] = x
            else:
                funds[(symbol, month)] = r["rows"]
        key = hashlib.sha256((fingerprint + "|" + kind + "|" + symbol + "|" + month + "|" + ",".join(map(str, times))).encode()).hexdigest()
        cache_file = cache / (key + ".json")
        sources.append({**r, "requested_minutes": times, "cache_path": str(cache_file) if cache_file.exists() else None,
                        "cache_sha256": bulk.sha(cache_file) if cache_file.exists() else None})
        print("EXT109_RISK_SOURCE", len(sources), "/", len(specs), kind, symbol, month, r["status"], flush=True)
    ledger = []
    for p in paths_doc["paths"]:
        if p["status"] == "verified":
            settled = env["settle"](SimpleNamespace(**p), marks, funds, statuses)
            category = "trade" if settled["risk_status"] == "verified" and not bool(settled["liq_proxy"]) else "unknown_risk"
            ledger.append({**p, **settled, "category": category})
        else:
            ledger.append({**p, "category": "no_order" if p["status"] in ("no_order_time", "known_risk_rejected") else "unknown_path"})
    source_doc = {"sources": sources, "fingerprint": fingerprint, "adapted_engine_sha256": engine_hash,
                  "source_engine_sha256": bulk.sha(risk.RISK_PATH), "note": "Official SHA source; minute marks are only a liquidation proxy."}
    (H / "三日风险来源.json").write_text(json.dumps(source_doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    output = {"ledger": ledger, "paths_sha256": bulk.sha(paths_path), "sources_sha256": bulk.sha(H / "三日风险来源.json"),
              "risk_code_sha256": bulk.sha(Path(__file__)), "note": "Unit paths only; unknown mark/funding or liquidation proxy is not assumed profitable."}
    (H / "三日单位风险账本.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT109_RISK_SETTLED", len(ledger), "source_groups", len(specs), flush=True)


if __name__ == "__main__":
    main()
