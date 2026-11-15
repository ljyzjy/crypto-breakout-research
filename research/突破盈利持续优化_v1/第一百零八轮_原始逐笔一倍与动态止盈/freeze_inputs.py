from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
R100 = P / "第一百轮_突破无进展提前退出"
R102 = P / "第一百零二轮_大柱持有损益核查"
R90 = P / "第九十轮_二零二二公开行情"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    synthetic = json.loads((H / "一倍止盈合成核验.json").read_text(encoding="utf-8"))
    assert synthetic["all_checks_pass"] and synthetic["engine_sha256"] == sha(H / "exit_1r.py")
    assert synthetic["test_sha256"] == sha(H / "test_exit_1r.py")
    baseline = json.loads((R98 / "原始逐笔汇总独立核验.json").read_text(encoding="utf-8"))
    assert baseline["all_checks_pass"] and baseline["detail_sha256"] == sha(R98 / "候选状态与单位账本.csv")
    assert baseline["report_sha256"] == sha(R98 / "原始逐笔汇总.json")
    risk = json.loads((R98 / "风险来源与账本独立核验.json").read_text(encoding="utf-8"))
    assert risk["all_checks_pass"] and risk["ledger_sha256"] == sha(R98 / "原始逐笔批次/单位净收益与风险.parquet")
    assert risk["input_sha256"] == sha(R98 / "原始逐笔批次/风险来源与结算.json")
    assert json.loads((R100 / "进展退出独立核验.json").read_text(encoding="utf-8"))["all_checks_pass"]
    assert json.loads((R102 / "大柱标签独立核验.json").read_text(encoding="utf-8"))["all_checks_pass"]
    files = [H / "研究方案.md", H / "exit_1r.py", H / "test_exit_1r.py", H / "一倍止盈合成核验.json",
             R98 / "研究冻结.json", R98 / "run_raw_2022.py", R98 / "原始逐笔汇总.json", R98 / "原始逐笔汇总独立核验.json",
             R98 / "风险来源与账本独立核验.json", R98 / "候选状态与单位账本.csv",
             R98 / "原始逐笔批次/逐笔信号.parquet", R98 / "原始逐笔批次/单位净收益与风险.parquet",
             R98 / "原始逐笔批次/风险来源与结算.json", R100 / "run_exit.py", R100 / "进展退出独立核验.json",
             R102 / "大柱标签独立核验.json", R102 / "事后大柱标签.parquet",
             R90 / "候选数据/固定十一币双币过滤潜在触价.parquet"]
    out = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "files": {str(p): sha(p) for p in files},
           "freeze_code_sha256": sha(Path(__file__)), "note": "Historical source inputs and 1R rule frozen before raw replay."}
    (H / "输入冻结.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": True, "files": len(files), "frozen_utc": out["frozen_utc"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
