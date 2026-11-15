from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
DATA = Path("D:/CodexResearch_2022_firstsec_20261115_v1")
QUALITY = P / "第九十轮_二零二二公开行情/二零二二分钟数据质量.json"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    q = json.loads(QUALITY.read_text(encoding="utf-8"))
    files = [H / "研究方案.md", QUALITY]
    for symbol in ("BTCUSDT", "ETHUSDT"):
        item = next(x for x in q["normalized"] if x["symbol"] == symbol)
        path = DATA / "normalized" / f"{symbol}_klines.parquet"
        assert item["status"] == "verified" and item["missing_minutes"] == 0 and item["rows"] == 570240
        assert sha(path) == item["sha256"]
        files.append(path)
    result = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "files": {str(x): sha(x) for x in files},
              "freeze_code_sha256": sha(Path(__file__)),
              "note": "Minute source frozen before this candidate screen; no future trade outcome is used."}
    (H / "输入冻结.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": True, "sources": len(files), "frozen_utc": result["frozen_utc"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
