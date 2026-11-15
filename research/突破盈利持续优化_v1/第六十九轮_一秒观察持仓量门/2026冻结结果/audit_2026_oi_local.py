"""Cross-check prepared OI points with the unchanged local source and export audited ledger rows."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import json
import math
import shutil
import time

import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
REF = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics")
SRC = P / "第五十八轮_BTCETH持仓量状态"
SNAP = P / "第六十二轮_一秒观察更早突破/2026完整批次_冻结"


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError("disk_headroom")
    while psutil.virtual_memory().available < 650 * 1024**2:
        if shutil.disk_usage(ROOT).free < 2_200_000_000:
            raise RuntimeError("disk_headroom")
        time.sleep(3)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            guard()
            block = f.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main():
    prepared_file = H / "2026持仓量候选点_待本地复核.json"
    prepared = json.loads(prepared_file.read_text(encoding="utf-8"))
    assert prepared["plan_sha256"] == sha(H / "冻结研究方案.md")
    assert prepared["snapshot_manifest_sha256"] == sha(SNAP / "完整快照哈希.json")
    qa = json.loads((SRC / "持仓量来源与质量核验.json").read_text(encoding="utf-8"))
    assert qa["all_official_samples_pass"] and qa["causality_tests"]["all_checks_pass"]
    assert sha(SRC / "持仓量来源与质量核验.json") == prepared["source_quality_sha256"]
    selected = defaultdict(list)
    source_hashes = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        path = REF / f"{symbol}-metrics-5m.parquet"
        source_hashes[symbol] = sha(path)
        assert source_hashes[symbol] == qa["source_parquet_sha256"][symbol]
        keys = {int(p["ts"]) for p in prepared["points"] if p["symbol"] == symbol}
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(columns=["sum_open_interest", "ts"], batch_size=8192, use_threads=False):
            guard()
            times = batch.column(1).cast(pa.int64()).to_numpy(zero_copy_only=False) // 1000
            values = batch.column(0).to_numpy(zero_copy_only=False)
            for idx in np.flatnonzero(np.isin(times, list(keys))):
                value = float(values[idx])
                selected[(symbol, int(times[idx]))].append(value if math.isfinite(value) else None)
        print("OBS69_LOCAL_OI_SOURCE", symbol, len(keys), flush=True)
    points = []
    for p in prepared["points"]:
        local = selected[(p["symbol"], int(p["ts"]))]
        submitted = p["values"]
        status = "verified"
        if len(local) != 1 or len(submitted) != 1:
            status = "missing_or_duplicate"
        elif local[0] is None or local[0] <= 0:
            status = "invalid_value"
        elif Decimal(str(local[0])) != Decimal(str(submitted[0])):
            status = "source_mismatch"
        points.append({**p, "local_values": local, "status": status})
    snap = json.loads((SNAP / "完整快照哈希.json").read_text(encoding="utf-8"))
    ledger_path = SNAP / "batch/动态池单位收益与风险.parquet"
    assert sha(ledger_path) == snap["files"]["batch/动态池单位收益与风险.parquet"]
    ledger = pq.read_table(ledger_path).to_pylist()
    assert len(ledger) == 26 and all(r["status"] == r["risk_status"] == "verified" and not r["liq_proxy"] for r in ledger)
    cols = ["observation_id", "variant", "decision_ts", "entry_ts", "entry_raw", "entry_fill", "exit_ts", "exit_raw", "exit_fill", "reason", "side", "funding", "entry_fee", "exit_fee", "net_per_unit_notional"]
    csv_path = H / "2026一秒观察已核验账本.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows({k: r[k] for k in cols} for r in ledger)
    result = {"all_checks_pass": all(p["status"] == "verified" for p in points), "year": "2026", "events": prepared["events"], "points": points, "point_status_counts": {s: sum(p["status"] == s for p in points) for s in sorted({p["status"] for p in points})}, "official_daily_archives": prepared["official_daily_archives"], "official_errors": prepared["errors"], "source_parquet_sha256": source_hashes, "prepared_sha256": sha(prepared_file), "ledger_csv_sha256": sha(csv_path), "plan_sha256": sha(H / "冻结研究方案.md"), "code_sha256": sha(Path(__file__)), "note": "Only selected points checked against same-exchange local archive; historical real-time publication times remain unverified."}
    (H / "2026持仓量逐点核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("OBS69_LOCAL_OI_AUDIT", result["point_status_counts"], "ledger_rows", len(ledger), flush=True)


if __name__ == "__main__":
    main()
