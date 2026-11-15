from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
R62 = P / "第六十二轮_一秒观察更早突破"
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R112 = P / "第一百一十二轮_突破后跟踪退出"
R113 = P / "第一百一十三轮_跟踪退出跨期验证"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    audit112 = json.loads((R112 / "跟踪退出汇总独立核验.json").read_text(encoding="utf-8"))
    assert audit112["all_checks_pass"] and audit112["summary_sha256"] == sha(R112 / "跟踪退出配对结果.json")
    audit113 = json.loads((R113 / "跨期跟踪退出汇总独立核验.json").read_text(encoding="utf-8"))
    assert audit113["all_checks_pass"] and audit113["summary_sha256"] == sha(R113 / "跨期跟踪退出配对结果.json")
    paths = [H / "研究方案.md", R98 / "原始逐笔批次/逐笔信号.parquet",
             R98 / "原始逐笔批次/单位净收益与风险.parquet", R112 / "跟踪退出单位账本.parquet",
             R112 / "跟踪退出配对明细.csv", R112 / "跟踪退出逐笔独立核验.json", R112 / "跟踪退出汇总独立核验.json",
             R112 / "跟踪退出配对结果.json", R113 / "跨期跟踪退出配对明细.csv", R113 / "跨期跟踪退出配对结果.json",
             R113 / "跨期跟踪退出汇总独立核验.json"]
    for year in ("2024", "2026"):
        snap = R62 / f"{year}完整批次_冻结"
        mf = json.loads((snap / "完整快照哈希.json").read_text(encoding="utf-8"))
        assert mf["all_checks_pass"]
        for name in ("batch/动态池逐笔信号筛查.parquet", "batch/动态池单位收益与风险.parquet"):
            file = snap / name
            assert sha(file) == mf["files"][name]
            paths.append(file)
        ledger = R113 / f"{year}跟踪退出风险账本.json"
        risk_audit = R113 / f"{year}跟踪退出风险独立核验.json"
        proof = json.loads(risk_audit.read_text(encoding="utf-8"))
        assert proof["all_checks_pass"] and proof["ledger_sha256"] == sha(ledger)
        paths.extend((snap / "完整快照哈希.json", ledger, risk_audit))
    doc = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "threshold": "0.50", "sources": {str(x): sha(x) for x in paths},
           "code_sha256": sha(Path(__file__)), "note": "Fixed historical entry and exit combination; not blind."}
    (H / "输入冻结.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": True, "sources": len(paths), "frozen_utc": doc["frozen_utc"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
