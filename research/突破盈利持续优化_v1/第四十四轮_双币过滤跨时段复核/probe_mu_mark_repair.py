"""Fetch official daily and monthly mark data and validate a missing-minute repair."""
import hashlib,io,json,shutil
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent
W=ROOT/'work'/'point_in_time_universe33'/'risk_cross44_repair';W.mkdir(parents=True,exist_ok=True)
M=60_000;start=1782740940000;times=list(range(start,1782741420000+M,M))
def digest(b):return hashlib.sha256(b).hexdigest()
def fetch(url):
    s=requests.Session();a=s.get(url+'.CHECKSUM',timeout=(15,50));a.raise_for_status();expected=a.text.strip().split()[0].lower()
    z=s.get(url,timeout=(15,100));z.raise_for_status();assert digest(z.content)==expected
    return z.content,expected
def read(body,lo,hi):
    d=pd.read_csv(io.BytesIO(body),compression='zip')[['open_time','open','high','low','close']].apply(pd.to_numeric,errors='raise')
    assert not d.open_time.duplicated().any() and d.open_time.between(lo,hi-1).all() and (d.open_time%M==0).all()
    a=d[['open','high','low','close']].to_numpy(float);assert np.isfinite(a).all() and (a>0).all()
    assert (d.high>=d[['open','low','close']].max(axis=1)).all() and (d.low<=d[['open','high','close']].min(axis=1)).all()
    return d.set_index('open_time').sort_index()
def main():
    assert shutil.disk_usage(ROOT).free>=2_200_000_000
    before=H/'2026_修复前冻结';before.mkdir(exist_ok=True)
    files={H/'跨时段双币过滤诊断.json':before/'跨时段双币过滤诊断.json',
           H/'跨时段独立核验.json':before/'跨时段独立核验.json',
           H/'2026_may_jul'/'动态池单位收益与风险.parquet':before/'动态池单位收益与风险.parquet',
           H/'2026_may_jul'/'动态池风险档案核验清单.json':before/'动态池风险档案核验清单.json'}
    hashes={}
    for a,b in files.items():
        if b.exists():assert digest(b.read_bytes())==digest(a.read_bytes())
        else:shutil.copy2(a,b)
        hashes[b.name]=digest(b.read_bytes())
    (before/'冻结哈希.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    base='https://data.binance.vision/data/futures/um/'
    monthly,ms=fetch(base+'monthly/markPriceKlines/MUUSDT/1m/MUUSDT-1m-2026-06.zip')
    daily,ds=fetch(base+'daily/markPriceKlines/MUUSDT/1m/MUUSDT-1m-2026-06-29.zip')
    manifest=json.loads((before/'动态池风险档案核验清单.json').read_text(encoding='utf-8'))
    old=next(x for x in manifest if x['contract']=='MUUSDT' and x['kind']=='markPriceKlines' and x['month']=='2026-06')
    assert old['status']=='verified' and old['sha256']==ms
    daylo=int(pd.Timestamp('2026-06-29',tz='UTC').timestamp()*1000);monthlo=int(pd.Timestamp('2026-06-01',tz='UTC').timestamp()*1000);monthhi=int(pd.Timestamp('2026-07-01',tz='UTC').timestamp()*1000)
    a=read(monthly,monthlo,monthhi);b=read(daily,daylo,daylo+86_400_000);overlap=a.index.intersection(b.index)
    agrees=bool(np.allclose(a.loc[overlap],b.loc[overlap],rtol=1e-10,atol=1e-12))
    absent=[t for t in times if t not in a.index];available=[t for t in absent if t in b.index]
    safe=agrees and len(absent)==len(times)==len(available)
    if safe:
        file=W/'MUUSDT-1m-2026-06-29.zip';file.write_bytes(daily);assert digest(file.read_bytes())==ds
    out={'monthly_sha256':ms,'daily_sha256':ds,'monthly_rows':len(a),'daily_rows':len(b),'overlap_rows':len(overlap),
         'overlap_agrees':agrees,'needed_minutes':len(times),'absent_from_month':len(absent),
         'missing_available_in_day':len(available),'repair_safe':safe,'needed_timestamps':times,
         'daily_local_path':str(W/'MUUSDT-1m-2026-06-29.zip') if safe else None,
         'note':'Only missing official daily mark minutes can be added; conflicting or missing data stays unknown.'}
    (H/'MU标记价日档来源核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CROSS44_MU_REPAIR_PROBE',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
