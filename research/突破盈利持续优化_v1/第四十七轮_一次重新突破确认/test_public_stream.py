"""Synthetic integrity, chunk-boundary, data-descriptor and corruption checks."""
import hashlib,io,json,zipfile
from pathlib import Path
import pandas as pd
from public_tape_stream import parse_stream,COLS
H=Path(__file__).resolve().parent
class NoSeek(io.BytesIO):
    def seekable(self):return False
    def seek(self,*args):raise io.UnsupportedOperation('no seek')
def make_zip(csv,descriptor=False,multiple=False):
    buf=NoSeek() if descriptor else io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('trades.csv',csv)
        if multiple:z.writestr('extra.csv','a\n1\n')
    return buf.getvalue()
def parse(data,step,expected=None):
    digest=expected or hashlib.sha256(data).hexdigest()
    windows={'a':(1000,1300),'b':(1800,2200)}
    return parse_stream((data[i:i+step] for i in range(0,len(data),step)),digest,windows,len(data))
def main():
    frame=pd.DataFrame({'agg_trade_id':range(1000),'price':[100+i/1000 for i in range(1000)],
        'quantity':[1+i/10000 for i in range(1000)],'first_trade_id':range(1000),'last_trade_id':range(1000),
        'transact_time':[1000+i for i in range(1000)],'is_buyer_maker':[('true' if i%2 else 'false') for i in range(1000)]})
    csv=frame.to_csv(index=False).encode();checks=0
    for descriptor in (False,True):
      data=make_zip(csv,descriptor)
      for step in (1,7,4096,262144):
        result,meta=parse(data,step)
        for name,(lo,hi) in {'a':(1000,1300),'b':(1800,2200)}.items():
            actual=pd.concat(result[name],ignore_index=True);expected=frame[(frame.transact_time>=lo)&(frame.transact_time<hi)][COLS].reset_index(drop=True)
            pd.testing.assert_frame_equal(actual[COLS],expected,check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
        checks+=1
    data=make_zip(csv)
    for bad in ('wrong_sha','truncated','multiple'):
        try:
            if bad=='wrong_sha':parse(data,97,'0'*64)
            elif bad=='truncated':parse(data[:-15],97)
            else:parse(make_zip(csv,multiple=True),97)
        except (ValueError,AssertionError,EOFError,zipfile.BadZipFile):pass
        else:raise AssertionError('accepted_'+bad)
    out={'all_checks_pass':True,'valid_zip_and_chunk_cases':checks,'wrong_sha_rejected':True,
         'truncated_zip_rejected':True,'multiple_members_rejected':True,'data_descriptor_checked':True,
         'stream_code_sha256':hashlib.sha256((H/'public_tape_stream.py').read_bytes()).hexdigest()}
    (H/'无落盘逐笔读取合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PUBLIC_TAPE_STREAM_SYNTHETIC',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
