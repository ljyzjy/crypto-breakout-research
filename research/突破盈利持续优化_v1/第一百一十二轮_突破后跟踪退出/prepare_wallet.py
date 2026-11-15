"""Adapt the audited 2022 wallet workflow to the fixed trailing paths."""
from pathlib import Path

H = Path(__file__).resolve().parent
R108 = H.parent / "第一百零八轮_原始逐笔一倍与动态止盈"
run = (R108 / "run_wallet.py").read_text(encoding="utf-8")
run_replacements = [
    ("一倍动态结果汇总.json", "跟踪退出配对结果.json"),
    ("一倍动态汇总独立核验.json", "跟踪退出汇总独立核验.json"),
    ("audit[\"result_sha256\"]", "audit[\"summary_sha256\"]"),
    ("一倍动态配对明细.csv", "跟踪退出配对明细.csv"),
    ("一倍止盈单位账本.parquet", "跟踪退出单位账本.parquet"),
    ('("baseline_paired", "one_r", "adaptive")', '("baseline_paired", "trailing")'),
    ('cohort == "one_r" or (cohort == "adaptive" and pair["adaptive_target"] == "1r")', 'cohort == "trailing"'),
    ('{"baseline_paired": "baseline_net", "one_r": "one_r_net", "adaptive": "adaptive_net"}', '{"baseline_paired": "original_net", "trailing": "trailing_net"}'),
]
for old, new in run_replacements:
    assert old in run, old
    run = run.replace(old, new)
run = run.replace('test_audit["summary_sha256"]', 'test_audit["result_sha256"]')
(H / "run_wallet.py").write_text(run, encoding="utf-8")

audit = (R108 / "audit_wallet.py").read_text(encoding="utf-8")
audit_replacements = [
    ("一倍动态结果汇总.json", "跟踪退出配对结果.json"),
    ("一倍动态汇总独立核验.json", "跟踪退出汇总独立核验.json"),
    ("一倍动态配对明细.csv", "跟踪退出配对明细.csv"),
    ("一倍止盈单位账本.parquet", "跟踪退出单位账本.parquet"),
    ('unit_audit["result_sha256"]', 'unit_audit["summary_sha256"]'),
    ('len(result["rows"]) == 24 and len(inputs) == 6', 'len(result["rows"]) == 16 and len(inputs) == 4'),
    ('cohort == "one_r" or (cohort == "adaptive" and u["adaptive_target"] == "1r")', 'cohort == "trailing"'),
    ('{"baseline_paired": "baseline_net", "one_r": "one_r_net", "adaptive": "adaptive_net"}', '{"baseline_paired": "original_net", "trailing": "trailing_net"}'),
]
for old, new in audit_replacements:
    assert old in audit, old
    audit = audit.replace(old, new)
(H / "audit_wallet.py").write_text(audit, encoding="utf-8")
print("trailing wallet runner and auditor prepared")
