from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    audit = json.loads((H / "分钟候选独立核验.json").read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["result_sha256"] == sha(H / "分钟候选筛查.json")
    test = json.loads((H / "双币试点合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["engine_sha256"] == sha(H / "dual_pilot_engine.py")
    assert test["test_sha256"] == sha(H / "test_dual_pilot.py")
    with (H / "分钟可能候选.csv").open(encoding="utf-8", newline="") as f:
        days = sorted({r["day_utc"] for r in csv.DictReader(f)})
    selected = sorted(days, key=lambda day: hashlib.sha256(("dual_pilot_2022_v1|" + day).encode()).hexdigest())[:3]
    assert selected == ["2022-03-14", "2022-05-07", "2022-11-24"]
    files = ["研究方案.md", "三日逐笔试点方案.md", "输入冻结.json", "分钟候选筛查.json", "分钟候选独立核验.json",
             "分钟可能候选.csv", "dual_pilot_engine.py", "test_dual_pilot.py", "双币试点合成核验.json"]
    out = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "selection": "first 3 SHA256(dual_pilot_2022_v1|date)",
           "days": selected, "files": {name: sha(H / name) for name in files}, "code_sha256": sha(Path(__file__)),
           "note": "Fixed historical pilot days before downloading and before any strategy PnL."}
    (H / "三日试点冻结.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": True, "days": selected, "frozen_utc": out["frozen_utc"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
