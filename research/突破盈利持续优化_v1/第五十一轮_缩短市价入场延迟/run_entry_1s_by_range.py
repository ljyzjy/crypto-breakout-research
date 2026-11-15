"""Use the tested, full-SHA ranged transport for one-second entry replay."""
import hashlib,json,sys
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;R48=P/'第四十八轮_固定一倍风险止盈'
sys.path.insert(0,str(R48));import public_range
sys.path.insert(0,str(H));import run_entry_1s as runner
def main(year):
    audit=json.loads((R48/'分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['range_code_sha256']==hashlib.sha256((R48/'public_range.py').read_bytes()).hexdigest()
    assert audit['stream_code_sha256']==hashlib.sha256((P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest()
    runner.direct.fetch=public_range.fetch;runner.main(year)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
