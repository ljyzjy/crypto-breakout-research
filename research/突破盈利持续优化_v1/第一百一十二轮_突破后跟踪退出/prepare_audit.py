"""Reuse the prior independent settlement auditor with a separate trailing decision."""
from pathlib import Path

H = Path(__file__).resolve().parent
source = H.parent / "第一百零八轮_原始逐笔一倍与动态止盈" / "audit_exit.py"
text = source.read_text(encoding="utf-8")
start, end = text.index("def evaluate(path, seq):"), text.index("\ndef main():")
text = text[:start] + "from audit_trailing_logic import evaluate\n\n" + text[end:]
replacements = [
    ('one_r', 'trailing'),
    ('一倍止盈逐笔独立核验.json', '跟踪退出逐笔独立核验.json'),
    ('一倍止盈单位账本.parquet', '跟踪退出单位账本.parquet'),
    ('一倍止盈回放质量.json', '跟踪退出回放质量.json'),
    ('run_raw_1r.py', 'run_trailing.py'),
    ('EXT108_', 'EXT112_'),
]
for old, new in replacements:
    assert old in text, old
    text = text.replace(old, new)
(H / "audit_trailing.py").write_text(text, encoding="utf-8")
print("independent trailing auditor prepared")
