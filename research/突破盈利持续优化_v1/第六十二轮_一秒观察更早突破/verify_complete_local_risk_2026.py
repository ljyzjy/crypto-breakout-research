"""Verify six existing local ZIPs needed by three 2026 risk paths."""
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import requests

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
BATCH = H / "2026一秒观察分批"
PLAN = H / "2026完整风险补验方案.md"
OUT = H / "2026完整风险补验"
DATA = ROOT / "work/breakout_forward_2026"
BASE = "https://data.binance.vision/data/futures/um/monthly/"
M = 60000


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError("disk_headroom")
    while psutil.virtual_memory().available < 500 * 1024**2:
        if shutil.disk_usage(ROOT).free < 2_200_000_000:
            raise RuntimeError("disk_headroom")
        time.sleep(3)


def main():
    guard()
    OUT.mkdir(exist_ok=True)
    frozen = OUT / "补验前冻结输入"
    frozen.mkdir(exist_ok=True)
    names = ["动态池逐笔信号筛查.parquet", "动态池延迟市价路径.parquet", "动态池逐笔提取质量.json", "逐笔执行冻结方案.json", "动态池单位收益与风险.parquet", "动态池单位筛查完整性.json"]
    hashes = {}
    for name in names:
        src, dst = BATCH / name, frozen / name
        digest = sha(src)
        if dst.exists():
            assert sha(dst) == digest, name
        else:
            shutil.copyfile(src, dst)
            assert sha(dst) == digest
        hashes[name] = digest
    ledger = pd.read_parquet(frozen / "动态池单位收益与风险.parquet")
    missing = ledger[~ledger.risk_status.eq("verified")]
    assert len(ledger) == 26 and len(missing) == 6 and missing.observation_id.nunique() == 3
    assert set(missing.contract) == {"AVAXUSDT", "NEARUSDT", "BTCUSDT"}
    required = {}
    for r in missing.itertuples(index=False):
        for ts in range(int(r.entry_ts) // M * M, int(r.exit_ts) // M * M + M, M):
            month = pd.Timestamp(ts, unit="ms", tz="UTC").strftime("%Y-%m")
            required.setdefault((r.contract, month), set()).add(ts)
    assert set(required) == {("AVAXUSDT", "2026-05"), ("NEARUSDT", "2026-05"), ("BTCUSDT", "2026-06")}
    cache = OUT / "补充风险缓存"
    cache.mkdir(exist_ok=True)
    archives = []
    with requests.Session() as session:
        for (symbol, month), times in sorted(required.items()):
            for kind in ("markPriceKlines", "fundingRate"):
                guard()
                name = f"{symbol}-1m-{month}.zip" if kind == "markPriceKlines" else f"{symbol}-fundingRate-{month}.zip"
                source = (DATA / kind / symbol / name).resolve()
                assert source.is_file() and source.is_relative_to(DATA.resolve())
                sub = f"{kind}/{symbol}/1m/{name}" if kind == "markPriceKlines" else f"{kind}/{symbol}/{name}"
                url = BASE + sub + ".CHECKSUM"
                response = session.get(url, timeout=(15, 50))
                response.raise_for_status()
                if len(response.content) > 4096:
                    raise ValueError("checksum_response_too_large")
                parts = response.text.strip().split()
                assert len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) and Path(parts[1]).name == name
                digest = sha(source)
                assert digest == parts[0].lower(), name
                d = pd.read_csv(source, compression="zip")
                cols = ["open_time", "open", "high", "low", "close"] if kind == "markPriceKlines" else ["calc_time", "funding_interval_hours", "last_funding_rate"]
                assert set(cols).issubset(d.columns)
                d = d[cols].apply(pd.to_numeric, errors="raise").rename(columns={"open_time": "ts", "calc_time": "ts"})
                assert np.isfinite(d.to_numpy(float)).all() and not d.ts.duplicated().any()
                lo = int(pd.Timestamp(month + "-01", tz="UTC").timestamp() * 1000)
                hi = int((pd.Timestamp(month + "-01", tz="UTC") + pd.offsets.MonthBegin(1)).timestamp() * 1000)
                assert d.ts.between(lo, hi - 1).all()
                if kind == "markPriceKlines":
                    assert (d.ts % M == 0).all() and (d[["open", "high", "low", "close"]] > 0).all().all()
                    assert (d.high >= d[["open", "low", "close"]].max(axis=1)).all() and (d.low <= d[["open", "high", "close"]].min(axis=1)).all()
                    d = d[d.ts.isin(times)]
                    assert set(d.ts.astype(int)) == times, (symbol, month, "missing mark minutes")
                else:
                    assert (d.funding_interval_hours > 0).all()
                record = {"kind": kind, "contract": symbol, "month": month, "status": "verified", "sha256": digest, "bytes": source.stat().st_size, "source_path": str(source), "checksum_url": url, "rows": d.to_dict("records")}
                key = hashlib.sha256((kind + "|" + symbol + "|" + month + "|" + digest + "|" + ",".join(map(str, sorted(times)))).encode()).hexdigest()
                out = cache / (key + ".json")
                out.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                archives.append({"kind": kind, "contract": symbol, "month": month, "status": "verified", "sha256": digest, "bytes": source.stat().st_size, "source_path": str(source), "checksum_url": url, "cache_path": str(out), "cache_sha256": sha(out), "required_timestamps": sorted(times) if kind == "markPriceKlines" else []})
                print("OBS62_EXTRA_LOCAL_RISK", kind, symbol, month, flush=True)
    result = {"all_checks_pass": True, "archives": archives, "pre_supplement_input_sha256": hashes, "plan_sha256": sha(PLAN), "code_sha256": sha(Path(__file__)), "note": "Six existing local ZIPs matched Binance checksum; source is same exchange. No ZIP downloaded."}
    (OUT / "补充风险来源核验.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS62_EXTRA_LOCAL_RISK_PASS", len(archives), flush=True)


if __name__ == "__main__":
    main()
