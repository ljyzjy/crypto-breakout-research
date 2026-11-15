"""Extend the audited cached-risk settlement with independently verified ZIPs."""
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
OUT = H / "2026完整风险补验"
BATCH = H / "2026一秒观察分批"


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    source = H / "settle_2026_cached.py"
    manifest_path = OUT / "补充风险来源核验.json"
    audit_path = OUT / "补充风险独立核验.json"
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert m["all_checks_pass"] and audit["all_checks_pass"]
    assert audit["manifest_sha256"] == sha(manifest_path) and audit["audit_sha256"] == sha(H / "audit_complete_local_risk_2026.py")
    for name, expected in m["pre_supplement_input_sha256"].items():
        assert sha(OUT / "补验前冻结输入" / name) == expected
        assert sha(BATCH / name) == expected
    code = source.read_text(encoding="utf-8")
    needle = "    for x in local['archives']:\n        assert runner.sha(Path(x['source_path']))==x['sha256'] and runner.sha(Path(x['cache_path']))==x['cache_sha256']\n"
    assert code.count(needle) == 1
    insertion = "    local['archives'].extend(json.loads((H/'2026完整风险补验'/'补充风险来源核验.json').read_text(encoding='utf-8'))['archives'])\n"
    revised = code.replace(needle, insertion + needle, 1)
    scope = {"__file__": str(source), "__name__": "obs62_extended_audited_risk"}
    exec(compile(revised, str(source), "exec"), scope)
    scope["main"]()
    status = json.loads((BATCH / "动态池单位筛查完整性.json").read_text(encoding="utf-8"))
    result = {"original_settlement_code_sha256": sha(source), "extra_manifest_sha256": sha(manifest_path), "extra_audit_sha256": sha(audit_path), "supplemented_risk_status": status, "ledger_sha256": sha(BATCH / "动态池单位收益与风险.parquet"), "note": "The original cached settlement code is left untouched; four preexisting and six extra verified local ZIP entries were used."}
    (OUT / "补验后账本状态.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OBS62_EXTRA_SETTLEMENT", json.dumps(status, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
