"""Independently reconstruct all 2022 quarter bounds and hindsight-only candidates."""
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import psutil
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
DATA = Path("D:/CodexResearch_2022_firstsec_20261115_v1")
Q = 900_000


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def present(sym, day):
    name = f"{sym}-trades-{day}.zip"
    return any((DATA / folder / name).is_file() for folder in ("raw_2022_full_trades", "same_phase_extra_raw", "independent_raw_trade_samples"))


def read_quarters(sym):
    path = DATA / "normalized" / f"{sym}_klines.parquet"
    table = pq.read_table(path, columns=["ts", "open", "high", "low", "close", "volume", "trade_count"])
    cols = {n: table[n].combine_chunks().to_numpy(zero_copy_only=False) for n in table.column_names}
    ts = cols["ts"].astype(np.int64)
    assert len(ts) == 570240 and np.all(np.diff(ts) == 60000) and np.all(ts % 60000 == 0)
    assert int(ts[0]) == int(datetime(2021, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert len(ts) % 15 == 0 and int(ts[0]) % Q == 0
    v = np.column_stack([cols[x] for x in ("open", "high", "low", "close", "volume", "trade_count")]).astype(float)
    ok = np.isfinite(v).all(axis=1) & (v[:, :4] > 0).all(axis=1)
    ok &= (v[:, 1] >= np.maximum.reduce((v[:, 0], v[:, 3], v[:, 2])))
    ok &= (v[:, 2] <= np.minimum.reduce((v[:, 0], v[:, 3], v[:, 1])))
    ok &= (v[:, 4] >= 0) & (v[:, 5] > 0)
    return {"ts": ts.reshape(-1, 15)[:, 0], "high": v[:, 1].reshape(-1, 15).max(axis=1),
            "low": v[:, 2].reshape(-1, 15).min(axis=1), "valid": ok.reshape(-1, 15).all(axis=1)}


def main():
    assert shutil.disk_usage(H).free >= 2_200_000_000 and shutil.disk_usage(DATA).free >= 5_000_000_000
    assert psutil.virtual_memory().available >= 850 * 1024**2
    result_path = H / "分钟候选筛查.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["code_sha256"] == sha(H / "screen_candidates.py")
    assert result["detail_sha256"] == sha(H / "分钟可能候选.csv")
    assert result["archives_sha256"] == sha(H / "逐笔档需求.csv")
    assert result["frozen_sha256"] == sha(H / "输入冻结.json")
    frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    for path, digest in frozen["files"].items():
        assert sha(Path(path)) == digest
    test = json.loads((H / "候选合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["code_sha256"] == result["code_sha256"] and test["test_sha256"] == sha(H / "test_screen.py")
    b, e = read_quarters("BTCUSDT"), read_quarters("ETHUSDT")
    assert np.array_equal(b["ts"], e["ts"])
    with (H / "分钟可能候选.csv").open(encoding="utf-8", newline="") as f:
        details = list(csv.DictReader(f))
    detail_by = {(int(r["quarter_ts"]), int(r["direction"])): r for r in details}
    assert len(detail_by) == len(details)
    start = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    known = unknown = longs = shorts = both = 0
    seen, needed, dates = set(), set(), set()
    for i, ts_ in enumerate(b["ts"]):
        ts = int(ts_)
        if not start <= ts < end:
            continue
        valid = i >= 16 and bool(b["valid"][i]) and bool(e["valid"][i]) and bool(b["valid"][i-16:i].all()) and bool(e["valid"][i-16:i].all())
        if not valid:
            unknown += 1
            assert (ts, 1) not in detail_by and (ts, -1) not in detail_by
            continue
        known += 1
        bu, bl = b["high"][i-16:i].max(), b["low"][i-16:i].min()
        eu, el = e["high"][i-16:i].max(), e["low"][i-16:i].min()
        up = bool(b["high"][i] > bu and e["high"][i] > eu)
        down = bool(b["low"][i] < bl and e["low"][i] < el)
        longs += up
        shorts += down
        both += up and down
        for direction, condition, x, y in ((1, up, bu, eu), (-1, down, bl, el)):
            assert ((ts, direction) in detail_by) == condition
            if not condition:
                continue
            row = detail_by[(ts, direction)]
            assert abs(float(row["btc_level"]) - x) < 1e-9 and abs(float(row["eth_level"]) - y) < 1e-9
            dt = datetime.fromtimestamp(ts / 1000, timezone.utc)
            day = dt.date().isoformat()
            assert row["day_utc"] == day
            assert (row["btc_day_present_unverified"] == "True") == present("BTCUSDT", day)
            assert (row["eth_day_present_unverified"] == "True") == present("ETHUSDT", day)
            prev = (dt.date() - timedelta(days=1)).isoformat() if dt.hour == dt.minute == 0 else ""
            assert row["previous_day_needed"] == prev
            for symbol in ("BTCUSDT", "ETHUSDT"):
                needed.add((symbol, day))
                if prev:
                    needed.add((symbol, prev))
            dates.add(day)
            seen.add((ts, direction))
    assert known + unknown == 35040 and seen == set(detail_by)
    assert (known, unknown, longs, shorts, both) == (result["known_quarters"], result["unknown_quarters"],
                                                     result["possible_long"], result["possible_short"], result["both_directions_possible_quarters"])
    assert len({ts for ts, _ in seen}) == result["possible_quarters"] and len(dates) == result["candidate_dates"]
    with (H / "逐笔档需求.csv").open(encoding="utf-8", newline="") as f:
        archives = list(csv.DictReader(f))
    assert {(r["symbol"], r["day"]) for r in archives} == needed
    assert all((r["present_unverified"] == "True") == present(r["symbol"], r["day"]) for r in archives)
    assert len(archives) == result["archive_files_needed"]
    assert sum(r["present_unverified"] == "True" for r in archives) == result["archive_files_present_unverified"]
    assert sum(r["present_unverified"] == "False" for r in archives) == result["archive_files_missing"]
    for sym, data in (("BTCUSDT", b), ("ETHUSDT", e)):
        assert int((~data["valid"]).sum()) == result["source_quality"][sym]["invalid_quarters"]
    audit = {"all_checks_pass": True, "quarters_checked": known + unknown, "candidate_direction_rows_checked": len(seen),
             "archive_requirements_checked": len(needed), "result_sha256": sha(result_path),
             "audit_code_sha256": sha(Path(__file__)), "note": "Independent reshaped-minute and rolling-loop screen; not simultaneous execution."}
    (H / "分钟候选独立核验.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
