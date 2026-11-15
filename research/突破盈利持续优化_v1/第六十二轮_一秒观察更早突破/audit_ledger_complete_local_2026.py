"""Run the original independent ledger audit with six audited extra sources."""
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
OUT = H / "2026完整风险补验"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    extra_path = OUT / "补充风险来源核验.json"
    audit_path = OUT / "补充风险独立核验.json"
    extra = json.loads(extra_path.read_text(encoding="utf-8"))
    verified = json.loads(audit_path.read_text(encoding="utf-8"))
    assert extra["all_checks_pass"] and verified["all_checks_pass"]
    assert verified["manifest_sha256"] == sha(extra_path) and verified["audit_sha256"] == sha(H / "audit_complete_local_risk_2026.py")
    original = H / "audit_ledger.py"
    code = original.read_text(encoding="utf-8")
    needle = "    for file in files:\n"
    assert code.count(needle) == 1
    addition = "    supplement=json.loads((H/'2026完整风险补验'/'补充风险来源核验.json').read_text(encoding='utf-8'))\n    for x in supplement['archives']:\n        assert hashlib.sha256(Path(x['cache_path']).read_bytes()).hexdigest()==x['cache_sha256']\n        files.append(Path(x['cache_path']))\n"
    scope = {"__file__": str(original), "__name__": "obs62_extended_independent_ledger_audit"}
    exec(compile(code.replace(needle, addition + needle, 1), str(original), "exec"), scope)
    scope["main"]("2026")
    result_path = H / "2026一秒观察账本独立核验.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["all_checks_pass"]
    metadata = {"all_checks_pass": True, "original_ledger_audit_sha256": sha(original), "supplement_manifest_sha256": sha(extra_path), "supplement_independent_audit_sha256": sha(audit_path), "ledger_audit_result_sha256": sha(result_path), "note": "Original ledger audit logic retained, with six separately verified cached source entries added."}
    (OUT / "完整账本扩展核验记录.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS62_FULL_LOCAL_LEDGER_AUDIT", json.dumps(metadata, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
