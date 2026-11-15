"""Normalize verified 2024 archives and report gaps, without filling observations."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent/'work'/'breakout_2024_11'
RAW=ROOT/'raw';OUT=ROOT/'normalized';OUT.mkdir(parents=True,exist_ok=True)
manifest=json.loads((HERE/'2024公开档案校验清单.json').read_text(encoding='utf-8'))
index={(x['kind'],x['contract'],x['month']):x for x in manifest['records']}
contracts=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
months=[f'2024-{m:02}' for m in range(1,13)]
coverage=[]
for c in contracts:
  for kind in ['klines','markPriceKlines','fundingRate']:
    pieces=[]
    for month in (['2023-12',*months] if kind=='klines' else months):
        rec=index[(kind,c,month)];assert rec['status'] in ('verified','verified_cached')
        suffix='fundingRate' if kind=='fundingRate' else '1m'
        path=RAW/kind/c/f'{c}-{suffix}-{month}.zip'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==rec['sha256']
        d=pd.read_csv(path,compression='zip')
        if kind=='fundingRate':
            wanted=['calc_time','funding_interval_hours','last_funding_rate']
            assert set(wanted)<=set(d.columns);d=d[wanted].rename(columns={'calc_time':'ts'})
        else:
            wanted=['open_time','open','high','low','close']
            if kind=='klines':wanted+=['volume','quote_volume','count','taker_buy_quote_volume']
            assert set(wanted)<=set(d.columns);d=d[wanted].rename(columns={'open_time':'ts','count':'trade_count'})
        for col in d.columns:d[col]=pd.to_numeric(d[col],errors='coerce')
        assert d.ts.notna().all();d.ts=d.ts.astype('int64')
        start=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)
        end=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        assert d.ts.between(start,end-1).all() and not d.ts.duplicated().any()
        if kind!='fundingRate':assert (d.ts%60_000==0).all()
        expected=int((end-start)//60_000) if kind!='fundingRate' else None
        cov={'contract':c,'kind':kind,'month':month,'rows':len(d),'expected_minutes':expected,
             'missing_minutes':expected-len(d) if expected is not None else None}
        coverage.append(cov);pieces.append(d)
    data=pd.concat(pieces,ignore_index=True).sort_values('ts').reset_index(drop=True)
    assert not data.ts.duplicated().any()
    if kind=='fundingRate':
        assert np.isfinite(data[['funding_interval_hours','last_funding_rate']].to_numpy()).all()
        assert (data.funding_interval_hours>0).all()
    data.to_parquet(OUT/f'{c}_{kind}.parquet',index=False)
  print('2024_NORMALIZED',c,flush=True)
pd.DataFrame(coverage).to_csv(HERE/'2024分钟覆盖.csv',index=False,encoding='utf-8-sig')
missing=[x for x in coverage if x['missing_minutes'] not in (None,0)]
report={'contracts':len(contracts),'archives_verified':manifest['verified'],'archives_expected':manifest['expected'],
        'records':len(coverage),'incomplete_minute_records':missing,'source':'Binance public archives with verified SHA256',
        'note':'No missing-price imputation; contract universe was selected from the later 2026 pool.'}
(HERE/'2024数据质量.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('2024_DATA_PREPARED',json.dumps(report,ensure_ascii=False),flush=True)
