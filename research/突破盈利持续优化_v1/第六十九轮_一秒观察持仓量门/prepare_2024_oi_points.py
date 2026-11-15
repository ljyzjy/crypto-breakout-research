"""Select time-causal OI from unchanged local archives after 2024 replay is frozen."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import io
import json
import math
import re
import shutil
import time
import urllib.request
import zipfile

import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
SRC = P / "第五十八轮_BTCETH持仓量状态"
SNAP = P / "第六十二轮_一秒观察更早突破/2024完整批次_冻结"
REF = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics")


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


def day_of(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")


def fetch(url, limit):
    guard()
    with urllib.request.urlopen(url, timeout=45) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("response_too_large")
    return body


def main():
    snapshot_file = SNAP / "完整快照哈希.json"
    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert snapshot["all_checks_pass"] and snapshot["known_groups"] == 95 and snapshot["original_unknown"] == 16
    assert json.loads((SNAP / "support/2024一秒观察账本独立核验.json").read_text(encoding="utf-8"))["all_checks_pass"]
    ledger_path = SNAP / "batch/动态池单位收益与风险.parquet"
    assert sha(ledger_path) == snapshot["files"]["batch/动态池单位收益与风险.parquet"]
    ledger_all = pq.read_table(ledger_path).to_pylist()
    ledger = [r for r in ledger_all if r["status"] == r["risk_status"] == "verified" and r["liq_proxy"] is False]
    assert ledger and len({(r["observation_id"], r["variant"]) for r in ledger}) == len(ledger)
    events = {}
    for r in ledger:
        obs, decision = r["observation_id"], int(r["decision_ts"])
        now = ((decision - 900000) // 300000) * 300000
        assert 900000 <= decision - now < 1200000
        item = {"observation_id": obs, "decision_ts": decision, "oi_t0": now, "oi_previous": now - 3600000}
        if obs in events:
            assert events[obs] == item
        events[obs] = item
    required = {(sym, t) for e in events.values() for sym in ("BTCUSDT", "ETHUSDT") for t in (e["oi_t0"], e["oi_previous"])}
    days = sorted({day_of(ts) for _, ts in required})
    sample_days = {days[0], days[-1]}
    qa_path = SRC / "持仓量来源与质量核验.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    assert qa["all_official_samples_pass"] and qa["causality_tests"]["all_checks_pass"]
    prior_path = SRC / "持仓量所需时间点.json"
    assert sha(prior_path) == json.loads((SRC / "持仓量门跨期对照.json").read_text(encoding="utf-8"))["oi_input_sha256"]
    prior = {(r["symbol"], int(r["ts"])): r["values"] for r in json.loads(prior_path.read_text(encoding="utf-8"))}
    selected, daily = defaultdict(list), defaultdict(list)
    source_hashes = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        path = REF / f"{symbol}-metrics-5m.parquet"
        source_hashes[symbol] = sha(path)
        assert source_hashes[symbol] == qa["source_parquet_sha256"][symbol]
        keys = {ts for sym, ts in required if sym == symbol}
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(columns=["sum_open_interest", "ts"], batch_size=8192, use_threads=False):
            guard()
            times = batch.column(1).cast(pa.int64()).to_numpy(zero_copy_only=False) // 1000
            vals = batch.column(0).to_numpy(zero_copy_only=False)
            for idx in np.flatnonzero(np.isin(times, list(keys))):
                value = float(vals[idx])
                selected[(symbol, int(times[idx]))].append(value if math.isfinite(value) else None)
            for day in sample_days:
                start = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
                for idx in np.flatnonzero((times >= start) & (times < start + 86400000)):
                    value = float(vals[idx])
                    daily[(symbol, day)].append((int(times[idx]), value if math.isfinite(value) else None))
        print("OBS69_2024_LOCAL_SOURCE", symbol, len(keys), flush=True)
    archives, errors, bad_days = [], [], set()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for day in sorted(sample_days):
            try:
                name = f"{symbol}-metrics-{day}.zip"
                url = f"https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{name}"
                parts = fetch(url + ".CHECKSUM", 4096).decode("utf-8").strip().split()
                assert len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) and Path(parts[1]).name == name
                blob = fetch(url, 2_000_000)
                digest = hashlib.sha256(blob).hexdigest()
                assert digest == parts[0].lower()
                official = []
                with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                    names = [x for x in archive.namelist() if not x.endswith("/")]
                    assert names == [name.replace(".zip", ".csv")]
                    with io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", newline="") as stream:
                        for row in csv.DictReader(stream):
                            assert row["symbol"] == symbol
                            dt = datetime.fromisoformat(row["create_time"])
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            ts = int(dt.timestamp() * 1000)
                            assert day_of(ts) == day and ts % 300000 == 0
                            official.append((ts, Decimal(row["sum_open_interest"])))
                local = sorted(daily[(symbol, day)])
                official.sort(key=lambda x: x[0])
                assert len(local) == len(official)
                for (lt, lv), (ot, ov) in zip(local, official):
                    assert lt == ot and lv is not None and Decimal(str(lv)) == ov
                archives.append({"symbol": symbol, "day": day, "sha256": digest, "bytes": len(blob), "rows_checked": len(official), "url": url})
                print("OBS69_2024_OI_SAMPLE", symbol, day, flush=True)
            except Exception as exc:
                bad_days.add((symbol, day))
                errors.append({"symbol": symbol, "day": day, "error": type(exc).__name__ + ":" + str(exc)[:160]})
                print("OBS69_2024_OI_SAMPLE_UNKNOWN", symbol, day, type(exc).__name__, flush=True)
    points = []
    for sym, ts in sorted(required):
        values = selected[(sym, ts)]
        status = "verified"
        if len(values) != 1:
            status = "missing_or_duplicate"
        elif values[0] is None or values[0] <= 0:
            status = "invalid_value"
        elif (sym, ts) in prior and (len(prior[(sym, ts)]) != 1 or Decimal(str(values[0])) != Decimal(str(prior[(sym, ts)][0]))):
            status = "prior_cache_mismatch"
        elif (sym, day_of(ts)) in bad_days:
            status = "official_sample_unavailable"
        points.append({"symbol": sym, "ts": ts, "values": values, "status": status})
    csv_path = H / "2024一秒观察已核验账本.csv"
    cols = ["observation_id", "variant", "decision_ts", "entry_ts", "entry_raw", "entry_fill", "exit_ts", "exit_raw", "exit_fill", "reason", "side", "funding", "entry_fee", "exit_fee", "net_per_unit_notional"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows({k: r[k] for k in cols} for r in ledger)
    result = {"all_checks_pass": all(p["status"] == "verified" for p in points), "year": "2024", "events": list(events.values()), "points": points, "point_status_counts": {s: sum(p["status"] == s for p in points) for s in sorted({p["status"] for p in points})}, "official_daily_archives": archives, "official_errors": errors, "source_parquet_sha256": source_hashes, "prior_cache_sha256": sha(prior_path), "ledger_csv_sha256": sha(csv_path), "snapshot_manifest_sha256": sha(snapshot_file), "plan_sha256": sha(H / "冻结研究方案.md"), "code_sha256": sha(Path(__file__)), "note": "Official daily checks cover only two preselected dates; actual historical arrival times remain unverified."}
    (H / "2024持仓量逐点核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("OBS69_2024_OI_POINTS", len(events), result["point_status_counts"], "samples", len(archives), "errors", len(errors), flush=True)


if __name__ == "__main__":
    main()
