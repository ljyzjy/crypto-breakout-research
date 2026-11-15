"""Adapt the established independent risk auditor to this isolated ledger."""
from pathlib import Path

H = Path(__file__).resolve().parent
source = H.parent / "第七十轮_一秒观察一倍止盈/audit_1r_ledger.py"
text = source.read_text(encoding="utf-8")
replacements = [
    ("H = Path(__file__).resolve().parent\nM = 60000", "H = Path(__file__).resolve().parent\nP = H.parent\nsys.path.insert(0, str(P / '第九十八轮_二零二二原始逐笔全样本'))\nimport run_raw_2022 as bulk\nM = 60000"),
    ("{year}一倍止盈本地风险账本.json", "{year}跟踪退出风险账本.json"),
    ("sha(H / 'settle_1r_local.py')", "sha(H / 'settle_cross.py')"),
    ("{year}一倍止盈账本独立核验.json", "{year}跟踪退出风险独立核验.json"),
    ("        if shutil.disk_usage(H).free < 2_200_000_000 or psutil.virtual_memory().available < 250 * 1024 ** 2:\n            raise RuntimeError('resource_headroom')", "        bulk.runner.guard()"),
    ("def main(year):\n", "def main(year):\n    bulk.runner.guard(start=True)\n"),
    ("ONEOBS_1R_LEDGER_AUDIT", "EXT113_RISK_AUDIT"),
]
for old, new in replacements:
    assert old in text, old
    text = text.replace(old, new)
(H / "audit_cross_risk.py").write_text(text, encoding="utf-8")
print("independent cross-period risk auditor prepared")
