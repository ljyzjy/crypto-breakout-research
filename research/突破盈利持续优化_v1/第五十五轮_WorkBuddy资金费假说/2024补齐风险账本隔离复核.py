"""Run the existing independent ledger audit with output redirected here only."""
from pathlib import Path
import hashlib
import json

H = Path(__file__).resolve().parent
FAST = H.parent / "第五十一轮_缩短市价入场延迟"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    original = FAST / "audit_entry_1s_ledger.py"
    batch = FAST / "2024一秒入场分批"
    sources = [original, FAST / "2024一秒入场逐笔独立抽查.json",
               FAST / "2024一秒五秒配对对照.json", FAST / "2024一秒五秒逐笔配对结果.parquet",
               batch / "动态池单位收益与风险.parquet", batch / "动态池风险档案核验清单.json"]
    before = {str(p): sha(p) for p in sources}
    src = original.read_text(encoding="utf-8")
    old = "(H/f'{year}一秒入场账本独立核验.json').write_text"
    new = "(OUTPUT/'2024补齐风险账本独立核验.json').write_text"
    assert src.count(old) == 1
    code = src.replace(old, new)
    env = {"__name__": "isolated_ledger_audit", "__file__": str(original), "OUTPUT": H}
    exec(compile(code, str(original), "exec"), env)
    env["main"]("2024")
    assert before == {str(p): sha(p) for p in sources}
    audit_file = H / "2024补齐风险账本独立核验.json"
    audit = json.loads(audit_file.read_text(encoding="utf-8"))
    assert audit["all_checks_pass"] and audit["audited_one_second_paths"] == 93
    proof = {"all_checks_pass": True, "redirected_original_sha256": sha(original),
             "output_sha256": sha(audit_file), "input_sha256_before_after": before,
             "note": "Original independent risk-ledger audit reused; output isolated to this research folder."}
    (H / "2024补齐账本隔离复核清单.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ISOLATED_LEDGER_AUDIT", json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
