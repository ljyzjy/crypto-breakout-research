"""Reuse separately written rank and official-minute audits against the new period."""
from pathlib import Path
import hashlib
import json
import shutil
import time
import psutil

H = Path(__file__).resolve().parent
R43 = H.parent / "第四十三轮_旧十一币2023年复核"
NORM = H.parent.parent.parent / "work" / "breakout_forward_2026" / "normalized"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load_patched(path, replacements, output, candidate_dir):
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    env = {"__name__": "ext63_independent_audit", "__file__": str(path), "AUDIT_FILE": output}
    exec(compile(text, str(path), "exec"), env)
    env["H"] = candidate_dir
    return env


def main():
    while psutil.virtual_memory().available < 850 * 1024**2:
        if shutil.disk_usage(H).free < 2_200_000_000:
            raise RuntimeError("disk_headroom")
        time.sleep(3)
    if shutil.disk_usage(H).free < 2_200_000_000:
        raise RuntimeError("disk_headroom")
    prep = json.loads((H / "延伸候选准备质量.json").read_text(encoding="utf-8"))
    assert prep["parity_and_causality"]["all_checks_pass"]
    folder = H / "候选数据"
    for name, digest in prep["outputs_sha256"].items():
        assert sha(folder / name) == digest, name
    initial = dict(prep["outputs_sha256"])
    rank_source = R43 / "audit_old11_ranks.py"
    ranks = load_patched(rank_source,
        [("(H/'2023日小时排名独立核验.json').write_text", "AUDIT_FILE.write_text")],
        H / "延伸日小时排名独立核验.json", folder)
    ranks["NORM"] = NORM
    ranks["main"]()
    candidate_source = R43 / "audit_old11_candidates.py"
    candidates = load_patched(candidate_source,
        [("H/'2023双币过滤潜在触价.parquet'", "H/'固定十一币双币过滤潜在触价.parquet'"),
         ("(H/'2023候选特征独立核验.json').write_text", "AUDIT_FILE.write_text")],
        H / "延伸候选特征独立核验.json", folder)
    candidates["main"]()
    for name, digest in initial.items():
        assert sha(folder / name) == digest, name
    a, b = (H / "延伸日小时排名独立核验.json"), (H / "延伸候选特征独立核验.json")
    assert json.loads(a.read_text(encoding="utf-8"))["all_checks_pass"]
    assert json.loads(b.read_text(encoding="utf-8"))["all_checks_pass"]
    summary = {"all_checks_pass": True, "rank_audit_sha256": sha(a), "candidate_audit_sha256": sha(b),
               "candidate_source_sha256": sha(candidate_source), "rank_source_sha256": sha(rank_source),
               "inputs_unchanged": True, "wrapper_sha256": sha(Path(__file__)),
               "note": "Existing independent audit algorithms reused; output redirected to new period only."}
    (H / "延伸候选独立核验总表.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXT63_INDEPENDENT_AUDIT", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
