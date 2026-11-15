"""Prepare time-causal 2026 OI points without inspecting PnL."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import io
import json
import re
import shutil
import time
import urllib.request
import zipfile

import psutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
SRC = P / "第五十八轮_BTCETH持仓量状态"
SNAP = P / "第六十二轮_一秒观察更早突破/2026完整批次_冻结"
PLAN = H / "冻结研究方案.md"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def guard():
    while psutil.virtual_memory().available < 750 * 1024**2:
        if shutil.disk_usage(ROOT).free < 2_200_000_000:
            raise RuntimeError("disk_headroom")
        time.sleep(3)
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError("disk_headroom")


def fetch(url, limit):
    guard()
    with urllib.request.urlopen(url, timeout=45) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("response_too_large")
    return body


def dt_day(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")


def main():
    snap = json.loads((SNAP / "完整快照哈希.json").read_text(encoding="utf-8"))
    assert snap["all_checks_pass"] and snap["known_groups"] == 35 and snap["original_unknown"] == 4
    point_path = SRC / "持仓量所需时间点.json"
    prior = json.loads((SRC / "持仓量门跨期对照.json").read_text(encoding="utf-8"))
    assert sha(point_path) == prior["oi_input_sha256"]
    points = {}
    for x in json.loads(point_path.read_text(encoding="utf-8")):
        key = (x["symbol"], int(x["ts"]))
        assert key not in points
        points[key] = {"values": [str(v) for v in x["values"]], "source": "prior_local_point_cache"}
    events = []
    for f in sorted((SNAP / "checkpoints").glob("*.json")):
        assert sha(f) == snap["files"]["checkpoints/" + f.name]
        cp = json.loads(f.read_text(encoding="utf-8"))
        for row in cp["rows"]:
            if row["status"] != "qualified":
                continue
            decision = int(row["decision_ts"])
            now = ((decision - 900_000) // 300_000) * 300_000
            assert 900_000 <= decision - now < 1_200_000
            events.append({"observation_id": row["observation_id"], "decision_ts": decision, "oi_t0": now, "oi_previous": now - 3_600_000})
    assert len(events) == 13 and len({x["observation_id"] for x in events}) == 13
    required = {(sym, t) for e in events for sym in ("BTCUSDT", "ETHUSDT") for t in (e["oi_t0"], e["oi_previous"])}
    missing = {k for k in required if k not in points}
    days = sorted({(sym, dt_day(ts)) for sym, ts in missing})
    archives, errors = [], []
    for sym, day in days:
        try:
            name = f"{sym}-metrics-{day}.zip"
            url = f"https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{name}"
            parts = fetch(url + ".CHECKSUM", 4096).decode("utf-8").strip().split()
            assert len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) and Path(parts[1]).name == name
            body = fetch(url, 2_000_000)
            digest = hashlib.sha256(body).hexdigest()
            assert digest == parts[0].lower()
            parsed = defaultdict(list)
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                names = [x for x in archive.namelist() if not x.endswith("/")]
                assert names == [name.replace(".zip", ".csv")]
                text_stream = io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", newline="")
                for row in csv.DictReader(text_stream):
                    assert row["symbol"] == sym
                    dt = datetime.fromisoformat(row["create_time"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts = int(dt.timestamp() * 1000)
                    assert dt_day(ts) == day and ts % 300_000 == 0
                    val = Decimal(row["sum_open_interest"])
                    assert val.is_finite()
                    parsed[(sym, ts)].append(str(val))
            overlap = 0
            for key in set(parsed).intersection(points):
                assert len(parsed[key]) == len(points[key]["values"]) == 1
                assert Decimal(parsed[key][0]) == Decimal(points[key]["values"][0])
                overlap += 1
            for key in missing:
                if key[0] == sym and dt_day(key[1]) == day and key in parsed:
                    points[key] = {"values": parsed[key], "source": "official_daily_metrics", "archive_sha256": digest}
            archives.append({"symbol": sym, "day": day, "sha256": digest, "bytes": len(body), "url": url, "cache_overlap_points_checked": overlap})
            print("OBS69_OI_DAY", sym, day, flush=True)
        except Exception as exc:
            errors.append({"symbol": sym, "day": day, "error": type(exc).__name__ + ":" + str(exc)[:160]})
            print("OBS69_OI_UNAVAILABLE", sym, day, type(exc).__name__, flush=True)
    selected = []
    for sym, ts in sorted(required):
        item = points.get((sym, ts))
        selected.append({"symbol": sym, "ts": ts, "values": item["values"] if item else [], "source": item["source"] if item else "missing", "archive_sha256": item.get("archive_sha256") if item else None})
    valid = sum(len(x["values"]) == 1 and Decimal(x["values"][0]).is_finite() and Decimal(x["values"][0]) > 0 for x in selected)
    output = {"year": "2026", "events": events, "points": selected, "official_daily_archives": archives, "errors": errors, "required_points": len(required), "valid_points": valid, "prior_cache_sha256": sha(point_path), "source_quality_sha256": sha(SRC / "持仓量来源与质量核验.json"), "plan_sha256": sha(PLAN), "snapshot_manifest_sha256": sha(SNAP / "完整快照哈希.json"), "note": "Point preparation only, no PnL grouped; new official points still require local-source comparison before final results."}
    (H / "2026持仓量候选点_待本地复核.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS69_OI_PREPARED", len(events), len(required), valid, "errors", len(errors), flush=True)


if __name__ == "__main__":
    main()
