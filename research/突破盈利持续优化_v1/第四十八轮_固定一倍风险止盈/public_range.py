"""Read verified public ZIP ranges concurrently, preserving full-file SHA checks."""
import concurrent.futures,re,sys
from pathlib import Path
import psutil,requests
H=Path(__file__).resolve().parent;P=H.parent
sys.path.insert(0,str(P/'第四十七轮_一次重新突破确认'));import public_tape_stream as original
ORIGINAL_FETCH=original.fetch
MAX_BUFFER=100_000_000;PART=2_000_000;WORKERS=3
def _piece(url,start,end,total,guard):
    expected=f'bytes {start}-{end}/{total}';buf=bytearray()
    for attempt in range(3):
        try:
            if guard:guard()
            with requests.get(url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'},stream=True,timeout=(15,120)) as r:
                r.raise_for_status()
                if r.status_code!=206 or r.headers.get('Content-Range')!=expected:raise ValueError('invalid_http_range')
                for chunk in r.iter_content(chunk_size=256*1024):
                    if guard:guard()
                    buf.extend(chunk)
                    if len(buf)>end-start+1:raise ValueError('oversized_http_range')
            if len(buf)!=end-start+1:raise ValueError('truncated_http_range')
            return bytes(buf)
        except Exception:
            buf.clear()
            if attempt==2:raise
def fetch(contract,day,windows,guard=None):
    name=f'{contract}-aggTrades-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    if guard:guard()
    with requests.Session() as s:
        c=s.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();digest=c.text.strip().split()[0].lower()
        head=s.head(url,headers={'Accept-Encoding':'identity'},allow_redirects=True,timeout=(15,50));head.raise_for_status()
        size=int(head.headers.get('Content-Length','0'))
    if size<=0 or size>original.MAX_ARCHIVE:raise RuntimeError('archive_exceeds_stream_cap_or_unknown')
    if head.headers.get('Accept-Ranges','').lower()!='bytes' or size>MAX_BUFFER or size>psutil.virtual_memory().available//4:
        return ORIGINAL_FETCH(contract,day,windows,guard)
    specs=[(i,min(i+PART-1,size-1)) for i in range(0,size,PART)];parts={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures={pool.submit(_piece,url,start,end,size,guard):start for start,end in specs}
        for f in concurrent.futures.as_completed(futures):parts[futures[f]]=f.result()
    def chunks():
        for start,_ in specs:
            if guard:guard()
            yield parts.pop(start)
    rows,meta=original.parse_stream(chunks(),digest,windows,size)
    return rows,{'kind':'aggTrades','day':day,**meta,'reader':'sha256_verified_http_ranges'}
