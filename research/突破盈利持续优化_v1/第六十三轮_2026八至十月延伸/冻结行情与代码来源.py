"""Freeze pre-existing normalized inputs and original research code before extension."""
from pathlib import Path
import hashlib
import json

import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
REF = H.parent / "第四十六轮_固定十一加密币跨时段"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT",
           "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "NEARUSDT")


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    prior_path = REF / "小块来源冻结哈希.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    assert prior["plan_sha256"] == sha(REF / "冻结研究方案.md")
    assert json.loads((REF / "小块算法一致性核验.json").read_text(encoding="utf-8"))["all_checks_pass"]
    source = {}
    for sym in SYMBOLS:
        item = prior["sources"][f"2026_{sym}"]
        path = Path(item["path"])
        assert sha(path) == item["sha256"], sym
        parquet = pq.ParquetFile(path)
        first = last = None
        for i in range(parquet.metadata.num_row_groups):
            rg = parquet.metadata.row_group(i)
            c = next(rg.column(j) for j in range(rg.num_columns) if rg.column(j).path_in_schema == "ts")
            assert c.statistics and c.statistics.has_min_max
            first = c.statistics.min if first is None else min(first, c.statistics.min)
            last = c.statistics.max if last is None else max(last, c.statistics.max)
        assert first <= 1_775_001_600_000 and last >= 1_793_491_140_000
        source[sym] = {"path": str(path), "sha256": item["sha256"], "rows": parquet.metadata.num_rows,
                       "first_ts_ms": first, "last_ts_ms": last}
    dependencies = {}
    for group in ("code", "support"):
        for key, item in prior[group].items():
            path = Path(item["path"])
            assert sha(path) == item["sha256"], (group, key)
            dependencies[f"{group}:{key}"] = item
    out = {"plan_sha256": sha(H / "冻结研究方案.md"), "source_manifest_sha256": sha(prior_path),
           "source": source, "dependencies": dependencies, "freeze_code_sha256": sha(Path(__file__)),
           "note": "Source files are pre-existing normalized public data; only candidate period changes, no orders or PnL yet."}
    target = H / "行情代码冻结哈希.json"
    if target.exists():
        assert json.loads(target.read_text(encoding="utf-8")) == out
    else:
        target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXT63_FROZEN", len(source), "sources", len(dependencies), "dependencies", flush=True)


if __name__ == "__main__":
    main()
