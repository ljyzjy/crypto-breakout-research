"""Parse verified public archives without inferring missing prices or listings."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_forward_2026'
OUT=WORK/'normalized'; OUT.mkdir(parents=True,exist_ok=True)
plan=json.loads((HERE/'冻结研究方案.json').read_text(encoding='utf-8'))
manifest=json.loads((HERE/'公开数据校验清单.json').read_text(encoding='utf-8'))
records={(r['kind'],r['contract'],r['month']):r for r in manifest['records']}

def load_one(kind,c,month):
    r=records[(kind,c,month)]
    if r['status'] not in ('verified','verified_cached'):return None
    suffix='fundingRate' if kind=='fundingRate' else '1m'
    path=WORK/kind/c/f'{c}-{suffix}-{month}.zip'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=r['sha256']:raise ValueError('archive hash mismatch')
    d=pd.read_csv(path,compression='zip')
    if kind=='fundingRate':
        wanted=['calc_time','funding_interval_hours','last_funding_rate']
        if not set(wanted)<=set(d.columns):raise ValueError('unexpected funding schema')
        d=d[wanted].rename(columns={'calc_time':'ts'})
    else:
        wanted=['open_time','open','high','low','close']
        if kind=='klines':wanted+=['volume','quote_volume','count','taker_buy_quote_volume']
        if not set(wanted)<=set(d.columns):raise ValueError('unexpected kline schema')
        d=d[wanted].rename(columns={'open_time':'ts','count':'trade_count'})
    for col in d.columns:d[col]=pd.to_numeric(d[col],errors='coerce')
    if d.ts.isna().any():raise ValueError('invalid timestamp')
    d.ts=d.ts.astype('int64')
    start=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)
    end=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
    if not d.ts.between(start,end-1).all():raise ValueError('timestamp outside archive month')
    if kind!='fundingRate' and (d.ts%60_000!=0).any():raise ValueError('unaligned minute')
    return d

def main():
    coverage=[]
    for item in plan['fixed_pool']:
        c=item['contract']
        for kind in ['klines','markPriceKlines','fundingRate']:
            months=range(4,11) if kind=='klines' else range(5,11)
            pieces=[]
            for month in months:
                tag=f'2026-{month:02}'; d=load_one(kind,c,tag)
                if d is None:
                    coverage.append({'contract':c,'kind':kind,'month':tag,'status':records[(kind,c,tag)]['status'],'rows':0});continue
                if d.ts.duplicated().any():raise ValueError('duplicate inside archive')
                expected=int(((pd.Timestamp(tag+'-01')+pd.offsets.MonthBegin(1))-pd.Timestamp(tag+'-01')).total_seconds()/60)
                cov={'contract':c,'kind':kind,'month':tag,'status':'verified','rows':len(d),
                     'expected_minutes':expected if kind!='fundingRate' else None,
                     'missing_minutes':expected-len(d) if kind!='fundingRate' else None}
                coverage.append(cov);pieces.append(d)
            if pieces:
                out=pd.concat(pieces,ignore_index=True).sort_values('ts')
                if out.ts.duplicated().any():raise ValueError('duplicate across archives')
                out.to_parquet(OUT/f'{c}_{kind}.parquet',index=False)
        print('NORMALIZED',c,flush=True)
    path=HERE/'分钟数据覆盖.csv';pd.DataFrame(coverage).to_csv(path,index=False,encoding='utf-8-sig')
    report={'records':len(coverage),'archive_issues':len(manifest['missing_or_error']),
            'minute_missing_records':sum(1 for r in coverage if r.get('missing_minutes',0) not in (None,0)),
            'method':'Missing/zero data retained; no fills; only verified archives are parsed.',
            'plan_sha256':hashlib.sha256((HERE/'冻结研究方案.json').read_bytes()).hexdigest()}
    (HERE/'数据准备核对.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('NORMALIZED_READY',json.dumps(report),flush=True)

if __name__=='__main__':main()
