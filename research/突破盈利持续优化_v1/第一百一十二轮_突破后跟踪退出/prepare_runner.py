"""Reuse the already guarded raw-path runner with the frozen trailing engine."""
from pathlib import Path

H = Path(__file__).resolve().parent
source = H.parent / "第一百零八轮_原始逐笔一倍与动态止盈" / "run_raw_1r.py"
text = source.read_text(encoding="utf-8")
replacements = [
    ('Resumable 2022 raw-trade 1R paths', 'Resumable 2022 raw-trade trailing paths'),
    ('"ext108_exit_1r", H / "exit_1r.py"', '"ext112_trailing", H / "trailing.py"'),
    ('one_r_target', 'activated_giveback'),
    ('one_r', 'trailing'),
    ('一倍止盈单位账本.parquet', '跟踪退出单位账本.parquet'),
    ('一倍止盈回放质量.json', '跟踪退出回放质量.json'),
    ('EXT108_', 'EXT112_'),
]
for old, new in replacements:
    assert old in text, old
    text = text.replace(old, new)
(H / "run_trailing.py").write_text(text, encoding="utf-8")
print("guarded trailing runner prepared")
