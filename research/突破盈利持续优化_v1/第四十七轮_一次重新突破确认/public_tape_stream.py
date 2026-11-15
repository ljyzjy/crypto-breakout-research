"""Verify and incrementally decode one public ZIP without persisting the archive."""
import hashlib,io,struct,zlib
import pandas as pd,requests

COLS=['agg_trade_id','price','quantity','transact_time','is_buyer_maker']
MAX_ARCHIVE=400_000_000
MAX_EVENT_ROWS=500_000
def parse_stream(chunks,expected,windows,content_length=None):
    """Hash the complete ZIP and collect only requested tick windows before use."""
    digest=hashlib.sha256();size=0;head=bytearray();tail=bytearray();pending=bytearray()
    decoder=None;header=None;seen_header=False;blocks={key:[] for key in windows};counts={key:0 for key in windows}
    def consume(data,final=False):
        nonlocal header,seen_header
        pending.extend(data);last=pending.rfind(b'\n')
        if final and pending and last!=len(pending)-1:pending.extend(b'\n');last=len(pending)-1
        if last<0:
            if len(pending)>2_000_000:raise ValueError('oversized_csv_line')
            return
        part=bytes(pending[:last+1]);del pending[:last+1]
        if not seen_header:
            line,sep,part=part.partition(b'\n');assert sep
            header=line.rstrip(b'\r');names=header.decode('utf-8-sig').split(',')
            if not set(COLS).issubset(names):raise ValueError('unexpected_csv_header')
            seen_header=True
        if not part:return
        df=pd.read_csv(io.BytesIO(header+b'\n'+part),usecols=COLS,dtype={'is_buyer_maker':str})
        if df.empty:return
        t=df.transact_time.to_numpy('int64')
        for key,(lo,hi) in windows.items():
            x=df.loc[(t>=int(lo))&(t<int(hi))]
            if len(x):
                counts[key]+=len(x)
                if counts[key]>MAX_EVENT_ROWS:raise RuntimeError('event_window_exceeds_memory_cap')
                blocks[key].append(x)
    for chunk in chunks:
        if not chunk:continue
        size+=len(chunk)
        if size>MAX_ARCHIVE:raise RuntimeError('archive_exceeds_stream_cap')
        digest.update(chunk);tail.extend(chunk)
        if len(tail)>1_000_000:del tail[:-1_000_000]
        if decoder is None:
            head.extend(chunk)
            if len(head)<30:continue
            sig,version,flags,method,mtime,mdate,crc,csize,usize,fnlen,extralen=struct.unpack('<IHHHHHIIIHH',head[:30])
            if sig!=0x04034b50 or method!=8 or flags&1:raise ValueError('unsupported_zip_local_header')
            offset=30+fnlen+extralen
            if offset>100_000:raise ValueError('oversized_zip_header')
            if len(head)<offset:continue
            name=bytes(head[30:30+fnlen]).decode('utf-8')
            if not name.endswith('.csv'):raise ValueError('unexpected_zip_member')
            decoder=zlib.decompressobj(-15);chunk=bytes(head[offset:]);head.clear()
        if not decoder.eof:
            rest=chunk
            while rest and not decoder.eof:
                output=decoder.decompress(rest,1024*1024);rest=decoder.unconsumed_tail
                if output:consume(output)
                if not rest:break
    if decoder is None or not decoder.eof:raise ValueError('truncated_deflate_stream')
    consume(b'',final=True)
    if not seen_header or pending:raise ValueError('incomplete_csv')
    if content_length is not None and size!=int(content_length):raise ValueError('archive_size_mismatch')
    if digest.hexdigest()!=expected.lower():raise ValueError('checksum_mismatch')
    i=tail.rfind(b'PK\x05\x06')
    if i<0 or len(tail)-i<22:raise ValueError('missing_zip_central_directory')
    signature,disk,first,entries_disk,entries,total_size,offset,comment=struct.unpack('<4s4H2IH',tail[i:i+22])
    if signature!=b'PK\x05\x06' or disk or first or entries_disk!=1 or entries!=1 or i+22+comment!=len(tail):
        raise ValueError('unexpected_zip_directory')
    return blocks,{'sha256':digest.hexdigest(),'bytes':size,'windows':counts}
def fetch(contract,day,windows,guard=None):
    name=f'{contract}-aggTrades-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{contract}/{name}'
    s=requests.Session();check=s.get(url+'.CHECKSUM',timeout=(15,50));check.raise_for_status();expected=check.text.strip().split()[0].lower()
    with s.get(url,headers={'Accept-Encoding':'identity'},stream=True,timeout=(15,120)) as r:
        r.raise_for_status();length=r.headers.get('Content-Length')
        if length is not None and int(length)>MAX_ARCHIVE:raise RuntimeError('archive_exceeds_stream_cap')
        def checked_chunks():
            for chunk in r.iter_content(chunk_size=256*1024):
                if guard is not None:guard()
                yield chunk
        rows,meta=parse_stream(checked_chunks(),expected,windows,length)
    return rows,{'kind':'aggTrades','day':day,**meta}
