"""Independently check local risk-cache contents against checksum-verified ZIPs."""
import csv,hashlib,io,json,math,zipfile
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;M=60000
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-12,abs_tol=1e-12)
def main():
    manifest=H/'2026本地风险来源核验.json';z=json.loads(manifest.read_text(encoding='utf-8'))
    assert z['all_checks_pass'] and z['code_sha256']==sha(H/'verify_local_risk.py') and z['plan_sha256']==sha(H/'本地风险补验方案.md')
    snap=H/'2026中间批次_13候选';assert z['snapshot_sha256']==sha(snap/'中间快照哈希.json')
    old=pd.read_parquet(snap/'动态池单位收益与风险.parquet');old=old[old.risk_status.eq('missing_mark_archive')]
    required={}
    for r in old.itertuples(index=False):
        for ts in range(int(r.entry_ts)//M*M,int(r.exit_ts)//M*M+M,M):
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m');required.setdefault((r.contract,month),set()).add(ts)
    archives=0;records=0
    for a in z['archives']:
        file=Path(a['source_path']);cache=Path(a['cache_path']);assert sha(file)==a['sha256'] and sha(cache)==a['cache_sha256']
        rec=json.loads(cache.read_text(encoding='utf-8'));assert rec['sha256']==a['sha256'] and rec['kind']==a['kind']
        key=(a['contract'],a['month']);cached={int(x['ts']):x for x in rec['rows']};assert len(cached)==len(rec['rows'])
        source_rows={}
        with zipfile.ZipFile(file) as archive:
            names=[x for x in archive.namelist() if not x.endswith('/')];assert len(names)==1
            with archive.open(names[0]) as raw:
                with io.TextIOWrapper(raw,encoding='utf-8-sig',newline='') as reader:
                    for x in csv.DictReader(reader):
                        ts=int(x['open_time'] if a['kind']=='markPriceKlines' else x['calc_time'])
                        if a['kind']=='markPriceKlines' and ts not in required[key]:continue
                        assert ts not in source_rows;source_rows[ts]=x
        assert set(source_rows)==set(cached)
        if a['kind']=='markPriceKlines':assert set(cached)==required[key]
        for ts,row in source_rows.items():
            keys=('open','high','low','close') if a['kind']=='markPriceKlines' else ('funding_interval_hours','last_funding_rate')
            assert all(near(row[k],cached[ts][k]) for k in keys);records+=1
        archives+=1
    assert archives==4
    out={'all_checks_pass':True,'archives_checked':archives,'source_records_checked':records,
         'manifest_sha256':sha(manifest),'audit_sha256':sha(Path(__file__)),
         'note':'Independent CSV reconstruction from local ZIPs already matched to official checksum files.'}
    (H/'2026本地风险独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OBS62_LOCAL_RISK_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
