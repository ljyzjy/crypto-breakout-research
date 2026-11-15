from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R108 = P / "第一百零八轮_原始逐笔一倍与动态止盈"
R70 = P / "第七十轮_一秒观察一倍止盈"
R62 = P / "第六十二轮_一秒观察更早突破"
R102 = P / "第一百零二轮_大柱持有损益核查"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    test = json.loads((H / "分批算术合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["code_sha256"] == sha(H / "split_math.py") and test["test_sha256"] == sha(H / "test_split_math.py")
    a = json.loads((R108 / "一倍动态汇总独立核验.json").read_text(encoding="utf-8"))
    assert a["all_checks_pass"] and a["result_sha256"] == sha(R108 / "一倍动态结果汇总.json")
    assert a["detail_sha256"] == sha(R108 / "一倍动态配对明细.csv")
    paths = json.loads((R108 / "一倍止盈逐笔独立核验.json").read_text(encoding="utf-8"))
    assert paths["all_checks_pass"] and paths["ledger_sha256"] == sha(R108 / "一倍止盈单位账本.parquet")
    r98 = json.loads((R98 / "风险来源与账本独立核验.json").read_text(encoding="utf-8"))
    assert r98["all_checks_pass"] and r98["ledger_sha256"] == sha(R98 / "原始逐笔批次/单位净收益与风险.parquet")
    label = json.loads((R102 / "大柱标签独立核验.json").read_text(encoding="utf-8"))
    assert label["all_checks_pass"] and label["labels_sha256"] == sha(R102 / "事后大柱标签.parquet")
    files = [H / "研究方案.md", H / "split_math.py", H / "test_split_math.py", H / "分批算术合成核验.json",
             R108 / "一倍动态结果汇总.json", R108 / "一倍动态汇总独立核验.json", R108 / "一倍动态配对明细.csv",
             R108 / "一倍止盈单位账本.parquet", R108 / "一倍止盈逐笔独立核验.json",
             R98 / "原始逐笔批次/单位净收益与风险.parquet", R98 / "风险来源与账本独立核验.json",
             R102 / "事后大柱标签.parquet", R102 / "大柱标签独立核验.json"]
    for year in ("2024", "2026"):
        snap = R62 / f"{year}完整批次_冻结"
        manifest_path = snap / "完整快照哈希.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["all_checks_pass"] and manifest["year"] == year
        original = snap / "batch/动态池单位收益与风险.parquet"
        assert sha(original) == manifest["files"]["batch/动态池单位收益与风险.parquet"]
        alt = R70 / f"{year}一倍止盈本地风险账本.json"
        risk = R70 / f"{year}一倍止盈账本独立核验.json"
        audit = json.loads(risk.read_text(encoding="utf-8"))
        assert audit["all_checks_pass"] and audit["ledger_sha256"] == sha(alt)
        summary = R70 / f"{year}一倍止盈配对对照.json"
        proof = R70 / f"{year}一倍止盈汇总独立核验.json"
        chk = json.loads(proof.read_text(encoding="utf-8"))
        assert chk["all_checks_pass"] and chk["result_sha256"] == sha(summary)
        files.extend([manifest_path, original, alt, risk, summary, proof, snap / f"support/{year}一秒观察对照.json"])
    out = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "files": {str(p): sha(p) for p in files},
           "code_sha256": sha(Path(__file__)), "note": "Historical 1R/2R pair sources frozen before split metrics."}
    (H / "输入冻结.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": True, "files": len(files), "frozen_utc": out["frozen_utc"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
