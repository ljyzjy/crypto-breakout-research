"""Recover a stalled official ZIP with bounded range requests and full SHA verification."""
import hashlib
from pathlib import Path
import sys
import requests
import run_raw_2022 as bulk


def main(symbol,day):
    bulk.runner.guard(start=True)
    assert symbol=='DOGEUSDT' and day=='2022-11-02'
    name=f'{symbol}-trades-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/trades/{symbol}/{name}'
    check=requests.get(url+'.CHECKSUM',timeout=(10,30));check.raise_for_status();parts=check.text.strip().split()
    assert len(parts)>=2 and Path(parts[1]).name==name;expected=parts[0].lower()
    head=requests.head(url,timeout=(10,30));head.raise_for_status();size=int(head.headers['Content-Length']);assert 0<size<=800_000_000
    folder=bulk.runner.ROOT/'raw_2022_full_trades';target=folder/name;partial=folder/(name+'.range-partial')
    assert target.resolve().is_relative_to(bulk.runner.ROOT.resolve()) and partial.resolve().is_relative_to(folder.resolve())
    if target.exists():assert bulk.sha(target)==expected;print('EXT98_RANGE_PRESENT',name,flush=True);return
    digest=hashlib.sha256();step=4*1024*1024;total=0
    with partial.open('wb') as out:
        for start in range(0,size,step):
            bulk.runner.guard();end=min(size-1,start+step-1)
            with requests.get(url,headers={'Range':f'bytes={start}-{end}'},stream=True,timeout=(10,35)) as resp:
                resp.raise_for_status();assert resp.status_code==206 and resp.headers.get('Content-Range')==f'bytes {start}-{end}/{size}'
                count=0
                for chunk in resp.iter_content(256*1024):
                    bulk.runner.guard();out.write(chunk);digest.update(chunk);count+=len(chunk)
                assert count==end-start+1;total+=count
            print('EXT98_RANGE',total,'/',size,flush=True)
    assert total==size and digest.hexdigest()==expected and bulk.sha(partial)==expected
    if target.exists():
        assert bulk.sha(target)==expected
        partial.unlink()
    else:partial.replace(target)
    print('EXT98_RANGE_COMPLETE',name,size,flush=True)


if __name__=='__main__':
    assert len(sys.argv)==3;main(sys.argv[1],sys.argv[2])
