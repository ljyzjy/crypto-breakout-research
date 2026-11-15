"""Resume identical verified checkpoints with a tested public range transport."""
import hashlib,json,sys
from pathlib import Path
import public_range
import run_1r_later as runner
H=Path(__file__).resolve().parent;P=H.parent
def main(year):
    audit=json.loads((H/'分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['range_code_sha256']==hashlib.sha256((H/'public_range.py').read_bytes()).hexdigest()
    assert audit['stream_code_sha256']==hashlib.sha256((P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest()
    runner.direct.fetch=public_range.fetch
    runner.main(year)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2024','2026');main(sys.argv[1])
