"""Read-only audit of the reference funding data and three public monthly archives."""
from decimal import Decimal
from pathlib import Path
import csv
import hashlib
import io
import json
import urllib.request
import zipfile

import pandas as pd

H = Path(__file__).resolve().parent
REFERENCE = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\perp")
SOURCE = REFERENCE / "fnd_BTCUSDT.parquet"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rows(raw):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    return [(int(row["calc_time"]), int(row["funding_interval_hours"]),
             Decimal(row["last_funding_rate"])) for row in reader]


def get(url):
    with urllib.request.urlopen(url, timeout=25) as response:
        return response.read()


def main():
    df = pd.read_parquet(SOURCE).sort_values("dt").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["dt"], utc=True)
    df["day"] = df["dt"].dt.floor("D")
    offsets = (df["dt"] - df["dt"].dt.floor("h")).dt.total_seconds()
    grouped = df.groupby("day")
    valid_day = grouped.apply(
        lambda x: len(x) == 3 and set(x.dt.dt.hour) == {0, 8, 16}
        and x.dt.nunique() == 3 and x.funding_interval_hours.eq(8).all()
        and x.last_funding_rate.notna().all()
        and ((x.dt - x.dt.dt.floor("h")).dt.total_seconds() < 60).all(),
        include_groups=False,
    )
    expected_days = pd.date_range(df.day.min(), df.day.max(), freq="D")
    checks = {
        "rows": len(df), "days": len(valid_day), "expected_days": len(expected_days),
        "duplicate_timestamps": int(df.dt.duplicated().sum()),
        "invalid_days": int((~valid_day).sum()),
        "missing_dates": int(len(expected_days.difference(valid_day.index))),
        "max_seconds_after_hour": float(offsets.max()),
        "symbols": sorted(df.symbol.unique().tolist()),
        "interval_hours": sorted(df.funding_interval_hours.unique().tolist()),
    }
    assert checks["duplicate_timestamps"] == checks["invalid_days"] == checks["missing_dates"] == 0
    assert checks["symbols"] == ["BTCUSDT"] and checks["interval_hours"] == [8]
    result = {"source_sha256": sha(SOURCE.read_bytes()), "source_checks": checks, "samples": []}
    for month in ("2023-04", "2024-01", "2026-06"):
        name = f"BTCUSDT-fundingRate-{month}.zip"
        url = "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/" + name
        expected = get(url + ".CHECKSUM").decode().split()[0].lower()
        raw = get(url)
        assert sha(raw) == expected, (month, "official checksum mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            assert names == [name.replace(".zip", ".csv")]
            official_raw = archive.read(names[0])
        local_raw = (REFERENCE / names[0]).read_bytes()
        official, local = rows(official_raw), rows(local_raw)
        assert official == local, (month, "local csv differs numerically")
        start = pd.Timestamp(month + "-01", tz="UTC")
        end = start + pd.offsets.MonthBegin(1)
        subset = df[(df.dt >= start) & (df.dt < end)]
        parquet_rows = [(int(t.value // 1_000_000), int(i), float(r))
                        for t, i, r in zip(subset.dt, subset.funding_interval_hours,
                                           subset.last_funding_rate)]
        assert len(official) == len(parquet_rows)
        for (t1, i1, r1), (t2, i2, r2) in zip(official, parquet_rows):
            assert t1 == t2 and i1 == i2 and abs(float(r1) - r2) < 1e-15
        result["samples"].append({
            "month": month, "url": url, "official_zip_sha256": expected,
            "official_zip_bytes": len(raw), "official_csv_sha256": sha(official_raw),
            "local_csv_sha256": sha(local_raw), "rows": len(official),
            "local_csv_values_equal_official": True,
            "parquet_values_equal_official_within_1e-15": True,
        })
    result["all_checks_pass"] = True
    (H / "参考资金费来源与完整性核验.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
