"""Freeze existing auditable sources before recombining retry paths."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R47 = P / "第四十七轮_一次重新突破确认"
R106 = P / "第一百零六轮_一秒五秒分层入场"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    source = json.loads((R47 / "跨期输入冻结哈希.json").read_text(encoding="utf-8"))
    assert source["plan_sha256"] == sha(R47 / "冻结研究方案.md")
    prior = json.loads((R47 / "单次重试净账本独立核验.json").read_text(encoding="utf-8"))
    assert prior["all_checks_pass"] and prior["independent_retry_ledger_paths"] >= 1
    unit = json.loads((R106 / "分层入场单位结果.json").read_text(encoding="utf-8"))
    audit = json.loads((R106 / "分层入场独立核验.json").read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["result_sha256"] == sha(R106 / "分层入场单位结果.json")
    assert audit["detail_sha256"] == sha(R106 / "分层入场逐候选明细.csv")
    files = [H / "研究方案.md", R47 / "冻结研究方案.md", R47 / "跨期输入冻结哈希.json",
             R47 / "单次重试跨期单位对照.json", R47 / "单次重试净账本独立核验.json",
             R47 / "重试逐笔独立核验.json", R106 / "分层入场单位结果.json",
             R106 / "分层入场逐候选明细.csv", R106 / "分层入场独立核验.json"]
    assert json.loads((R47 / "重试逐笔独立核验.json").read_text(encoding="utf-8"))["all_checks_pass"]
    for year in ("2024", "2026"):
        old = R47 / "跨期冻结输入" / f"{year}_signal.parquet"
        candidates = R47 / "跨期冻结输入" / f"{year}_retry_candidates.parquet"
        assert sha(old) == source["inputs"][old.name] == unit["input_sha256"][year]["old_signal"]
        assert sha(candidates) == source["inputs"][candidates.name]
        base = pd.read_parquet(old)
        selected = base[base.status.eq("flow_filter_not_met") & (base.side * (base.raw_entry_5s - base.level) <= 0)]
        cand = pd.read_parquet(candidates)
        assert set(selected.observation_id) == set(cand.observation_id) and cand.observation_id.is_unique
        group = R47 / f"{year}重试分批"
        checks = json.loads((group / "风险输入哈希.json").read_text(encoding="utf-8"))
        for name, expected in checks.items():
            assert sha(group / name) == expected
        signals = pd.read_parquet(group / "动态池逐笔信号筛查.parquet")
        assert signals.observation_id.is_unique and set(signals.observation_id) == set(cand.observation_id)
        files.extend([old, candidates, group / "风险输入哈希.json", group / "动态池逐笔信号筛查.parquet",
                      group / "动态池延迟市价路径.parquet", group / "动态池单位收益与风险.parquet",
                      group / "动态池逐笔提取质量.json", group / "动态池风险档案核验清单.json"])
    out = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "files": {str(p): sha(p) for p in files},
           "freeze_code_sha256": sha(Path(__file__)),
           "note": "Existing historical sources only; selection rule fixed after prior experiment results."}
    (H / "输入冻结.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"frozen_utc": out["frozen_utc"], "files": len(files), "all_checks_pass": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
