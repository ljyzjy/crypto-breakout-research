import csv,hashlib,io
import availability_engine as e

def main():
    p=e.ROOT/'fee-protocol.json'
    freeze=e.ROOT/'fee-frozen.json'
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    if freeze.exists():assert e.base.read(freeze)['protocol_sha256']==sha
    else:e.base.dump(freeze,dict(created_utc=e.pd.Timestamp.now(tz='UTC').isoformat(),protocol_sha256=sha))
    for path,h in e.base.read(e.ROOT/'frozen.json')['files'].items():
        assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==h,path
    rows=[]
    for mode in e.NAMES:
        r=e.summary(e.cached_run('2025-01-01','2026-04-26',mode,.0005,0))
        r['scenario']='official_taker_reference';rows.append(r)
        print('Official fee reference',len(rows),'/14',mode,r['valid_for_comparison'],flush=True)
    e.base.dump(e.ROOT/'fee-reference.json',rows)
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (e.ROOT/'fee-reference.csv').write_text('\ufeff'+buf.getvalue(),encoding='utf-8')

if __name__=='__main__':main()
