"""Preselect six pilot quarters for an independent raw replay before viewing outcomes."""
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
    frozen = json.loads((H / "三日试点冻结.json").read_text(encoding="utf-8"))
    for name, digest in frozen["files"].items():
        assert sha(H / name) == digest
    with (H / "分钟可能候选.csv").open(encoding="utf-8", newline="") as f:
        choices = sorted({int(r["quarter_ts"]) for r in csv.DictReader(f) if r["day_utc"] in frozen["days"]})
    sample = sorted(choices, key=lambda ts: hashlib.sha256(("dual_audit_2022_v1|" + str(ts)).encode()).hexdigest())[:6]
    assert len(sample) == 6
    out = {"frozen_utc": datetime.now(timezone.utc).isoformat(), "sample_quarters": sample,
           "selection": "first 6 SHA256(dual_audit_2022_v1|quarter_ms)", "eligible_quarters": len(choices),
           "pilot_freeze_sha256": sha(H / "三日试点冻结.json"), "code_sha256": sha(Path(__file__)),
           "note": "Chosen before tick signal/path results; data-availability failures remain unresolved."}
    (H / "逐笔独立样本冻结.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": True, "eligible_quarters": len(choices), "samples": len(sample)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
