"""Binance public monthly OHLCV -> Freqtrade feather, with SHA256 verification.

Does not use account/trading endpoints or credentials. End month is exclusive.
"""
import argparse
import hashlib
import io
import json
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE = "https://data.binance.vision/data/spot/monthly/klines"


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def download_one(symbol, timeframe, month):
    filename = f"{symbol}-{timeframe}-{month}.zip"
    url = f"{BASE}/{symbol}/{timeframe}/{filename}"
    cache = ROOT / "user_data" / "data" / "archive"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / filename
    checksum_file = cache / (filename + ".CHECKSUM")
    expected = (checksum_file.read_bytes() if checksum_file.exists()
                else fetch(url + ".CHECKSUM"))
    blob = target.read_bytes() if target.exists() else fetch(url)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != expected.decode().split()[0]:
        raise ValueError(f"Checksum mismatch: {filename}")
    target.write_bytes(blob)
    checksum_file.write_bytes(expected)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        raw = pd.read_csv(archive.open(archive.namelist()[0]), header=None)
    frame = raw.iloc[:, :6].copy()
    frame.columns = ["date", "open", "high", "low", "close", "volume"]
    # Binance changed spot archive timestamps to microseconds from 2025-01.
    unit = "us" if int(frame["date"].iloc[0]) > 10**14 else "ms"
    frame["date"] = pd.to_datetime(frame["date"], unit=unit, utc=True)
    for column in frame.columns[1:]:
        frame[column] = frame[column].astype(float)
    return symbol, frame, {"file": filename, "url": url, "sha256": digest, "rows": len(frame)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2022-10")
    parser.add_argument("--end", default="2026-11", help="exclusive month")
    parser.add_argument("--timeframe", choices=["1h", "5m"], default="1h")
    parser.add_argument("--allow-gaps", action="store_true", help="Preserve and report gaps for explicit Freqtrade handling")
    args = parser.parse_args()
    months = pd.date_range(args.start + "-01", args.end + "-01", freq="MS", inclusive="left")
    if len(months) == 0:
        raise ValueError("Start month must precede end month")
    frames = {"BTCUSDT": [], "ETHUSDT": []}
    manifests = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [pool.submit(download_one, symbol, args.timeframe, month.strftime("%Y-%m"))
                for symbol in frames for month in months]
        for i, future in enumerate(as_completed(jobs), 1):
            symbol, frame, manifest = future.result()
            frames[symbol].append(frame)
            manifests.append(manifest)
            print(f"[{i}/{len(jobs)}] {manifest['file']}", flush=True)
    out = ROOT / "user_data" / "data" / "binance"
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    interval = pd.Timedelta(hours=1) if args.timeframe == "1h" else pd.Timedelta(minutes=5)
    for symbol, parts in frames.items():
        frame = pd.concat(parts).sort_values("date").reset_index(drop=True)
        if frame["date"].duplicated().any():
            raise ValueError(f"Duplicate timestamps: {symbol}")
        gaps = int((frame["date"].diff().dropna() != interval).sum())
        invalid = ((frame["high"] < frame[["open", "close", "low"]].max(axis=1))
                   | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
                   | (frame["volume"] < 0) | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1))
        gap_rows = frame.loc[frame["date"].diff() > interval, "date"].astype(str).tolist()
        if frame.isna().any().any() or invalid.any() or (gaps and not args.allow_gaps):
            raise ValueError(f"Invalid/missing OHLCV data: {symbol}, gap count={gaps}")
        target = out / f"{symbol[:-4]}_USDT-{args.timeframe}"
        frame.to_csv(target.with_suffix(".csv"), index=False)
        try:
            frame.to_feather(target.with_suffix(".feather"))
        except ImportError:
            print("pyarrow absent: CSV saved; rerun in Freqtrade environment to export feather.", flush=True)
        summary.append({"symbol": symbol, "rows": len(frame), "start": str(frame.date.min()),
                        "end": str(frame.date.max()), "gaps": gaps, "gap_end_times": gap_rows})
    report = {"timeframe": args.timeframe, "summary": summary,
              "files": sorted(manifests, key=lambda x: x["file"])}
    (out / f"manifest-{args.timeframe}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
