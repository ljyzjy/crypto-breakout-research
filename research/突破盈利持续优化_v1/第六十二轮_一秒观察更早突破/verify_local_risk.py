"""Verify existing LINK risk ZIPs against official checksum files, no ZIP downloads."""
import hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;ROOT=H.parent.parent.parent;M=60000
DATA=ROOT/'work'/'breakout_forward_2026';CACHE=ROOT/'work'/'oneobs62_2026'/'local_risk_cache'
BASE='https://data.binance.vision/data/futures/um/monthly/'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    snap=H/'2026中间批次_13候选';f=json.loads((snap/'中间快照哈希.json').read_text(encoding='utf-8'))
    assert f['all_checks_pass'] and all(sha(snap/n)==v for n,v in f['files'].items())
    ledger=pd.read_parquet(snap/'动态池单位收益与风险.parquet');missing=ledger[ledger.risk_status.eq('missing_mark_archive')]
    assert len(missing)==4 and set(missing.contract)=={'LINKUSDT'} and missing.observation_id.nunique()==2
    required={}
    for r in missing.itertuples(index=False):
        for ts in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m');required.setdefault((r.contract,month),set()).add(ts)
    assert set(required)=={('LINKUSDT','2026-05'),('LINKUSDT','2026-07')}
    CACHE.mkdir(parents=True,exist_ok=True);archives=[]
    with requests.Session() as s:
      for (symbol,month),times in sorted(required.items()):
       for kind in ('markPriceKlines','fundingRate'):
        name=f'{symbol}-1m-{month}.zip' if kind=='markPriceKlines' else f'{symbol}-fundingRate-{month}.zip'
        file=(DATA/kind/symbol/name).resolve();assert file.is_file() and file.is_relative_to(DATA.resolve())
        sub=f'{kind}/{symbol}/1m/{name}' if kind=='markPriceKlines' else f'{kind}/{symbol}/{name}'
        checksum=BASE+sub+'.CHECKSUM';r=s.get(checksum,timeout=(15,50));r.raise_for_status()
        if len(r.content)>4096:raise ValueError('unexpected_checksum_size')
        expected=r.text.strip().split()[0].lower();digest=sha(file)
        if digest!=expected:raise ValueError('local_archive_sha_mismatch:'+name)
        d=pd.read_csv(file,compression='zip');cols=['open_time','open','high','low','close'] if kind=='markPriceKlines' else ['calc_time','funding_interval_hours','last_funding_rate']
        if not set(cols).issubset(d.columns):raise ValueError('source_columns:'+name)
        d=d[cols].apply(pd.to_numeric,errors='raise').rename(columns={'open_time':'ts','calc_time':'ts'})
        if not np.isfinite(d.to_numpy(float)).all() or d.ts.duplicated().any():raise ValueError('nonfinite_or_duplicate:'+name)
        lo=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000);hi=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        if not d.ts.between(lo,hi-1).all():raise ValueError('outside_month:'+name)
        if kind=='markPriceKlines':
            if (d.ts%M!=0).any() or not (d[['open','high','low','close']]>0).all().all():raise ValueError('invalid_mark:'+name)
            if (d.high<d[['open','low','close']].max(axis=1)).any() or (d.low>d[['open','high','close']].min(axis=1)).any():raise ValueError('bad_ohlc:'+name)
            d=d[d.ts.isin(times)]
            if set(d.ts.astype(int))!=times:raise ValueError('required_mark_minute_missing:'+name)
        elif (d.funding_interval_hours<=0).any():raise ValueError('bad_funding_interval:'+name)
        record={'kind':kind,'contract':symbol,'month':month,'status':'verified','sha256':digest,'bytes':file.stat().st_size,
                'source_path':str(file),'checksum_url':checksum,'rows':d.to_dict('records')}
        key=hashlib.sha256((kind+'|'+symbol+'|'+month+'|'+digest+'|'+','.join(map(str,sorted(times)))).encode()).hexdigest()
        output=CACHE/(key+'.json');output.write_text(json.dumps(record,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        archives.append({'kind':kind,'contract':symbol,'month':month,'status':'verified','sha256':digest,
                         'bytes':file.stat().st_size,'source_path':str(file),'checksum_url':checksum,'cache_path':str(output),'cache_sha256':sha(output)})
        print('OBS62_LOCAL_RISK_VERIFIED',kind,symbol,month,flush=True)
    out={'all_checks_pass':True,'archives':archives,'snapshot_sha256':sha(snap/'中间快照哈希.json'),
         'plan_sha256':sha(H/'本地风险补验方案.md'),'code_sha256':sha(Path(__file__)),
         'note':'Local ZIPs matched official checksum text; same-exchange source, no ZIP was downloaded.'}
    (H/'2026本地风险来源核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_LOCAL_RISK_PASS',len(archives),flush=True)
if __name__=='__main__':main()
