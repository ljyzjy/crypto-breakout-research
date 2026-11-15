"""Stream local OI snapshots; verify preselected Binance public daily samples."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import io
import json
import math
import urllib.request
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
REF = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics")
EVENTS = P / "第五十五轮_WorkBuddy资金费假说" / "已核验机会及资金费门.csv"
SAMPLES = ("2023-04-01", "2024-01-15", "2026-06-01")
M, SLOT = 60_000, 300_000


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def time_keys(decision):
    t0 = ((int(decision) - 15 * M) // SLOT) * SLOT
    assert 15 * M <= int(decision) - t0 < 20 * M
    return t0, t0 - 60 * M


def selftest():
    t = int(datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc).timestamp() * 1000)
    a, b = time_keys(t)
    assert a == t - 15 * M and b == t - 75 * M
    a2, b2 = time_keys(t - 1)
    assert a2 == a - SLOT and b2 == b - SLOT
    return {"all_checks_pass": True, "checks": ["UTC boundary", "15-minute embargo", "exact 60-minute baseline"]}


def fetch(url):
    with urllib.request.urlopen(url, timeout=25) as response:
        return response.read()


def main():
    event_rows = {}
    with EVENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["year"], row["observation_id"])
            value = int(row["decision_ts"])
            if key in event_rows:
                assert event_rows[key] == value
            event_rows[key] = value
    required = {t for value in event_rows.values() for t in time_keys(value)}
    sample_days = {day: int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
                   for day in SAMPLES}
    selected = defaultdict(list)
    sample_rows = defaultdict(list)
    profiles, source_hashes = {}, {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        path = REF / f"{sym}-metrics-5m.parquet"
        source_hashes[sym] = digest(path)
        parquet = pq.ParquetFile(path)
        previous = None
        profile = {"rows": 0, "timestamp_null": 0, "oi_null_or_nonfinite": 0,
                   "oi_nonpositive": 0, "duplicate_adjacent_ts": 0, "out_of_order": 0,
                   "missing_slots_between_rows": 0, "off_grid_ts": 0}
        for batch in parquet.iter_batches(columns=["sum_open_interest", "ts"], batch_size=8192, use_threads=False):
            tarr = batch.column(1)
            profile["timestamp_null"] += tarr.null_count
            assert tarr.null_count == 0
            times = tarr.cast(pa.int64()).to_numpy(zero_copy_only=False) // 1000
            values = batch.column(0).to_numpy(zero_copy_only=False)
            profile["rows"] += len(times)
            profile["oi_null_or_nonfinite"] += int((~np.isfinite(values)).sum())
            profile["oi_nonpositive"] += int((np.isfinite(values) & (values <= 0)).sum())
            profile["off_grid_ts"] += int((times % SLOT != 0).sum())
            if len(times):
                if previous is not None:
                    diffs = np.diff(np.concatenate(([previous], times)))
                else:
                    profile["first_ts_ms"] = int(times[0])
                    diffs = np.diff(times)
                profile["duplicate_adjacent_ts"] += int((diffs == 0).sum())
                profile["out_of_order"] += int((diffs < 0).sum())
                profile["missing_slots_between_rows"] += int(np.maximum(diffs // SLOT - 1, 0).sum())
                previous = int(times[-1])
                profile["last_ts_ms"] = previous
            for t, v in zip(times, values):
                ts = int(t)
                if ts in required:
                    selected[(sym, ts)].append(float(v) if math.isfinite(v) else None)
                for day, start in sample_days.items():
                    if start <= ts < start + 24 * 60 * M:
                        sample_rows[(sym, day)].append((ts, float(v) if math.isfinite(v) else None))
        assert profile["rows"] == parquet.metadata.num_rows
        profiles[sym] = profile

    samples = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        for day in SAMPLES:
            name = f"{sym}-metrics-{day}.zip"
            url = f"https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{name}"
            claimed = fetch(url + ".CHECKSUM").decode().split()[0].lower()
            raw = fetch(url)
            checksum = hashlib.sha256(raw).hexdigest()
            assert checksum == claimed, (sym, day, "official ZIP checksum")
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = archive.namelist()
                assert names == [name.replace(".zip", ".csv")]
                body = archive.read(names[0])
            official = []
            for row in csv.DictReader(io.StringIO(body.decode("utf-8-sig"))):
                assert row["symbol"] == sym
                dt = datetime.fromisoformat(row["create_time"]).replace(tzinfo=timezone.utc)
                official.append((int(dt.timestamp() * 1000), Decimal(row["sum_open_interest"])))
            local = sorted(sample_rows[(sym, day)])
            official.sort(key=lambda x: x[0])
            assert len(official) == len(local), (sym, day, "count", len(official), len(local))
            for (ot, ov), (lt, lv) in zip(official, local):
                assert ot == lt and lv is not None and math.isclose(float(ov), lv, rel_tol=1e-12, abs_tol=1e-9), (sym, day, ot)
            samples.append({"symbol": sym, "day": day, "official_zip_url": url,
                "official_zip_sha256": checksum, "official_csv_sha256": hashlib.sha256(body).hexdigest(),
                "rows_compared": len(official), "values_match": True})

    selected_rows = [{"symbol": sym, "ts": ts, "values": selected[(sym, ts)]}
                     for sym in ("BTCUSDT", "ETHUSDT") for ts in sorted(required)]
    summary = Counter((r["symbol"], len(r["values"])) for r in selected_rows)
    out = {"plan_sha256": digest(H / "冻结研究方案.md"), "script_sha256": digest(Path(__file__)),
           "event_csv_sha256": digest(EVENTS), "source_parquet_sha256": source_hashes,
           "unique_known_events": len(event_rows), "required_distinct_timestamps": len(required),
           "selected_key_multiplicity": {f"{sym}:{n}": count for (sym, n), count in sorted(summary.items())},
           "global_profiles": profiles, "official_daily_samples": samples,
           "causality_tests": selftest(), "all_official_samples_pass": True,
           "release_lag_note": "Archive timestamp is not historical arrival time; 15-minute lag remains an assumption."}
    (H / "持仓量所需时间点.json").write_text(json.dumps(selected_rows, ensure_ascii=False), encoding="utf-8")
    out["selected_keys_sha256"] = digest(H / "持仓量所需时间点.json")
    (H / "持仓量来源与质量核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
