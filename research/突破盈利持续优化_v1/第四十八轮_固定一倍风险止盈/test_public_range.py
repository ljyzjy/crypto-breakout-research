"""Check HTTP range validation and compare a real tape with the stream reader."""
import hashlib,json,sys
from pathlib import Path
import pandas as pd
import public_range as ranged
H=Path(__file__).resolve().parent;P=H.parent
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as standard
class Fake:
    def __init__(self,wrong=False):self.status_code=206;self.headers={'Content-Range':'bad' if wrong else 'bytes 0-3/4'}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):pass
    def iter_content(self,chunk_size):yield b'ab';yield b'cd'
def main():
    get=ranged.requests.get
    try:
        ranged.requests.get=lambda *a,**k:Fake()
        assert ranged._piece('https://example.invalid/x',0,3,4,None)==b'abcd'
        ranged.requests.get=lambda *a,**k:Fake(wrong=True)
        try:ranged._piece('https://example.invalid/x',0,3,4,None);raise AssertionError('bad range accepted')
        except ValueError:pass
    finally:ranged.requests.get=get
    D=P/'第四十六轮_固定十一加密币跨时段'/'逐笔冻结输入';d=pd.read_parquet(D/'2024_candidates.parquet').set_index('observation_id')
    obs='opening|ADAUSDT|1708362000000';e=d.loc[obs];window={obs:(int(e.trigger_minute),int(e.quarter_end)+60_000)}
    a,ma=standard.fetch(e.contract,e.day,window);b,mb=ranged.fetch(e.contract,e.day,window)
    assert mb.get('reader')=='sha256_verified_http_ranges' and ma['sha256']==mb['sha256'] and ma['bytes']==mb['bytes'] and ma['windows']==mb['windows']
    x=pd.concat(a[obs],ignore_index=True).reset_index(drop=True);y=pd.concat(b[obs],ignore_index=True).reset_index(drop=True)
    pd.testing.assert_frame_equal(x,y,check_dtype=True,check_exact=True)
    out={'all_checks_pass':True,'synthetic_range_header_checks':True,'real_source':{'observation_id':obs,'sha256':ma['sha256'],
         'bytes':ma['bytes'],'rows':len(x)},'range_code_sha256':hashlib.sha256((H/'public_range.py').read_bytes()).hexdigest(),
         'stream_code_sha256':hashlib.sha256((P/'第四十七轮_一次重新突破确认'/'public_tape_stream.py').read_bytes()).hexdigest(),
         'note':'HTTP ranges are assembled in byte order; complete archive SHA and ZIP structure are verified before any checkpoint.'}
    (H/'分段逐笔读取核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PUBLIC_RANGE_REAL_PASS',len(x),flush=True)
if __name__=='__main__':main()
