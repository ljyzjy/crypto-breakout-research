"""Reuse fully audited 2022 risk cache rows only when they cover every newly needed minute."""
import hashlib
import json
from pathlib import Path
import shutil
import pandas as pd
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent;B=H/'原始逐笔批次'


def main():
    bulk.runner.guard(start=True)
    proof=json.loads((bulk.R90/'风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    manifest_path=bulk.R90/'一秒回放批次/风险来源与结算.json';assert proof['all_checks_pass'] and proof['input_sha256']==bulk.sha(manifest_path)
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))['sources']
    old={(x['kind'],x['contract'],x['month']):x for x in manifest if x['status']=='verified'}
    sig=pd.read_parquet(B/'逐笔信号.parquet');paths=pd.read_parquet(B/'模拟路径.parquet')
    valid=paths[paths.status.eq('verified')].merge(sig[['observation_id','contract']],on='observation_id',validate='many_to_one')
    required={}
    for r in valid.itertuples(index=False):
        for ts in range(int(r.entry_ts)//60000*60000,int(r.exit_ts)//60000*60000+60000,60000):
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m');required.setdefault((r.contract,month),set()).add(ts)
    specs=[(kind,sym,month,sorted(times) if kind=='markPriceKlines' else [])
           for (sym,month),times in sorted(required.items()) for kind in ('markPriceKlines','fundingRate')]
    fp=hashlib.sha256((bulk.sha(B/'逐笔信号.parquet')+bulk.sha(B/'模拟路径.parquet')+bulk.sha(H/'settle_risk.py')).encode()).hexdigest()
    folder=bulk.runner.ROOT/'raw_2022_full_risk';folder.mkdir(exist_ok=True);records=[]
    for kind,sym,month,times in specs:
        bulk.runner.guard();info=old.get((kind,sym,month))
        if not info:continue
        source=Path(info['cache_path']);assert bulk.sha(source)==info['cache_sha256']
        cached=json.loads(source.read_text(encoding='utf-8'));assert cached['status']=='verified' and cached['sha256']==info['sha256']
        if kind=='markPriceKlines' and not set(times).issubset({int(x['ts']) for x in cached['rows']}):continue
        key=hashlib.sha256((fp+'|'+kind+'|'+sym+'|'+month+'|'+','.join(map(str,times))).encode()).hexdigest();target=folder/(key+'.json')
        assert target.resolve().is_relative_to(folder.resolve())
        if target.exists():assert bulk.sha(target)==info['cache_sha256']
        else:shutil.copy2(source,target)
        assert bulk.sha(target)==info['cache_sha256']
        records.append({'kind':kind,'contract':sym,'month':month,'source_cache_sha256':info['cache_sha256'],
                        'archive_sha256':info['sha256'],'required_minutes':len(times),'target':str(target)})
    out={'seeded_count':len(records),'required_count':len(specs),'records':records,'fingerprint':fp,
         'source_audit_sha256':bulk.sha(bulk.R90/'风险来源与账本独立核验.json'),'code_sha256':bulk.sha(Path(__file__)),
         'note':'Subset coverage confirmed; new batch audit still independently re-downloads official risk archives.'}
    (H/'风险缓存复用记录.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT98_CACHE_SEEDED',len(records),'/',len(specs),flush=True)


if __name__=='__main__':main()
