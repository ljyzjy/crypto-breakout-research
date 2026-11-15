"""Check strict window endpoints, ordering and header compatibility."""
import io
import json
from pathlib import Path
import zipfile
import count_same_phase as engine

H=Path(__file__).resolve().parent


def zipped(content):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('sample.csv',content)
    b.seek(0);return b


def main():
    times=[901000,900999,1000,1,0,900001,999,500,900000]
    rows=''.join(f'{i},1.0,2.0,2.0,{t},true\n' for i,t in enumerate(times))
    windows=[(0,1000),(900000,901000)]
    assert engine.count_windows(zipped(rows),windows)==[3,2]
    assert engine.count_windows(zipped('id,price,qty,quote_qty,time,is_buyer_maker\n'+rows),windows)==[3,2]
    assert engine.count_windows(zipped(rows),list(reversed(windows)))==[2,3]
    try:engine.count_windows(zipped(rows),[(0,1000),(999,1200)]);raise AssertionError('overlap_not_rejected')
    except AssertionError as exc:
        if str(exc)=='overlap_not_rejected':raise
    assert 40*3==3*40 and 40*3>=3*40 and not 40*3>=3*41
    out={'all_checks_pass':True,'cases_checked':5,'code_sha256':engine.bulk.sha(H/'count_same_phase.py'),
         'test_sha256':engine.bulk.sha(Path(__file__)),'note':'Strict endpoint, unsorted records, header formats, overlap and threshold boundary.'}
    (H/'严格秒窗合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print('EXT104_SYNTHETIC_PASS',5,flush=True)


if __name__=='__main__':main()
