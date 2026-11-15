"""Settle raw replay paths using verified monthly funding and mark-price archives."""
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
import run_raw_2022 as bulk

H=Path(__file__).resolve().parent; B=H/'原始逐笔批次'
sys.path.insert(0,str(bulk.R90)); import settle_risk_2022 as original


def main():
    bulk.runner.guard(start=True); bulk.frozen(); quality=json.loads((B/'逐笔准备质量.json').read_text(encoding='utf-8'))
    assert quality['fingerprint']==bulk.fingerprint() and quality['code_sha256']==bulk.sha(H/'build_batch.py')
    assert quality['signals_sha256']==bulk.sha(B/'逐笔信号.parquet') and quality['paths_sha256']==bulk.sha(B/'模拟路径.parquet')
    assert quality['completed_groups']==quality['expected_groups']
    sig=pd.read_parquet(B/'逐笔信号.parquet'); paths=pd.read_parquet(B/'模拟路径.parquet')
    valid=paths[paths.status.eq('verified')].merge(sig[['observation_id','contract','side','source_year','decision_ts','quarter_end']],on='observation_id',validate='many_to_one')
    required={}
    for row in valid.itertuples(index=False):
        for ts in range(int(row.entry_ts)//60000*60000,int(row.exit_ts)//60000*60000+60000,60000):
            month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
            required.setdefault((row.contract,month),set()).add(ts)
    specs=[(kind,sym,month,sorted(times) if kind=='markPriceKlines' else [])
           for (sym,month),times in sorted(required.items()) for kind in ('markPriceKlines','fundingRate')]
    env,adapted=original.risk_namespace(); work=bulk.runner.ROOT/'raw_2022_full_risk'; work.mkdir(parents=True,exist_ok=True)
    env['WORK']=work; env['FINGERPRINT']=hashlib.sha256((bulk.sha(B/'逐笔信号.parquet')+bulk.sha(B/'模拟路径.parquet')+bulk.sha(Path(__file__))).encode()).hexdigest()
    existing=json.loads((bulk.R90/'一秒回放批次/风险来源与结算.json').read_text(encoding='utf-8'))['sources']
    old={(x['kind'],x['contract'],x['month']):x for x in existing}
    marks={};funds={};statuses={};sources=[]
    for spec in specs:
        bulk.runner.guard(); r=env['task'](spec); key=spec[:3]; statuses[key]=r['status']
        if r['status']=='verified':
            if key in old: assert old[key]['sha256']==r['sha256']
            if r['kind']=='markPriceKlines':
                for x in r['rows']: marks[(r['contract'],int(x['ts']))]=x
            else: funds[(r['contract'],r['month'])]=r['rows']
        cache_id=hashlib.sha256((env['FINGERPRINT']+'|'+spec[0]+'|'+spec[1]+'|'+spec[2]+'|'+','.join(map(str,spec[3]))).encode()).hexdigest()
        cache=work/(cache_id+'.json')
        sources.append({**{k:v for k,v in r.items() if k!='rows'},'cache_path':str(cache) if cache.exists() else None,
                        'cache_sha256':bulk.sha(cache) if cache.exists() else None})
        print('EXT98_RISK',len(sources),'/',len(specs),r['status'],spec[0],spec[1],spec[2],flush=True)
    entries=[env['settle'](r,marks,funds,statuses) for r in valid.itertuples(index=False)]
    ledger=pd.concat([valid.reset_index(drop=True),pd.DataFrame(entries)],axis=1)
    if not len(ledger): ledger['risk_status']=pd.Series(dtype='object')
    ledger.to_parquet(B/'单位净收益与风险.parquet',index=False)
    out={'fingerprint':bulk.fingerprint(),'code_sha256':bulk.sha(Path(__file__)),'input_quality_sha256':bulk.sha(B/'逐笔准备质量.json'),
         'signal_sha256':bulk.sha(B/'逐笔信号.parquet'),'paths_sha256':bulk.sha(B/'模拟路径.parquet'),
         'ledger_sha256':bulk.sha(B/'单位净收益与风险.parquet'),'source_engine_sha256':bulk.sha(original.RISK_PATH),
         'adapted_engine_sha256':adapted,'sources':sources,'source_count':len(specs),
         'risk_statuses':ledger.risk_status.value_counts().to_dict(),
         'note':'Minute mark-risk proxy and funding; not exchange liquidation or account equity.'}
    (B/'风险来源与结算.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXT98_SETTLED',len(valid),len(sources),flush=True)


if __name__=='__main__':main()
