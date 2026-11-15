"""Resume the same 2023 checkpoint keys using a tested ranged transport."""
import hashlib,json
from pathlib import Path
import public_range
import run_1r_2023_by_size as wrapper
H=Path(__file__).resolve().parent;P=H.parent
def main():
    audit=json.loads((H/'分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['range_code_sha256']==hashlib.sha256((H/'public_range.py').read_bytes()).hexdigest()
    assert audit['stream_code_sha256']==hashlib.sha256((P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest()
    wrapper.r.direct.fetch=public_range.fetch
    wrapper.main()
if __name__=='__main__':main()
