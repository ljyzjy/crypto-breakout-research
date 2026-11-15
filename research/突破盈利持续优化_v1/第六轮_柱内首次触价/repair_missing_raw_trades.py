"""Repair aggregate-trade gaps using separately verified original trades."""
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent
M=60_000
def main():
    label=sys.argv[1] if len(sys.argv)>1 else '后续'
    path=HERE/f'逐笔首次触价与五秒入场_{label}.parquet'
    meta_path=HERE/f'逐笔触价档案校验_{label}.json'
    d=pd.read_parquet(path);meta=json.loads(meta_path.read_text(encoding='utf-8'))
    missing=d[d.status.isin(['no_trigger_data','ohlc_trade_mismatch'])]
    repairs=[]
    for (contract,day),group in missing.groupby(['contract','day']):
        name=f'{contract}-trades-{day}.zip'
        url=f'https://data.binance.vision/data/futures/um/daily/trades/{contract}/{name}'
        check=requests.get(url+'.CHECKSUM',timeout=(12,45));check.raise_for_status();sha=check.text.strip().split()[0].lower()
        res=requests.get(url,timeout=(12,120));res.raise_for_status();body=res.content
        assert hashlib.sha256(body).hexdigest()==sha
        needed=[]
        for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['id','price','time'],chunksize=200_000):
            times=chunk.time.to_numpy(np.int64);mask=np.zeros(len(chunk),dtype=bool)
            for r in group.itertuples(index=False):mask|=(times>=r.trigger_minute)&(times<min(r.trigger_minute+2*M,r.quarter_end))
            if mask.any():needed.append(chunk.loc[mask])
        rawticks=pd.concat(needed,ignore_index=True).sort_values(['time','id'],kind='mergesort').reset_index(drop=True)
        for idx,row in group.iterrows():
            t=int(row.trigger_minute);qend=int(row.quarter_end)
            x=rawticks[(rawticks.time>=t)&(rawticks.time<min(t+2*M,qend))].copy()
            first=x[x.time<t+M];assert len(first)>0
            year=str(row.source_year);norm=ROOT/'work'/('breakout_november_2026' if year=='2026' else f'breakout_{year}_11')/'normalized'
            minute=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','open','high','low','close','trade_count']).set_index('ts')
            bar=minute.loc[t]
            assert len(first)==int(bar.trade_count)
            assert np.isclose(first.price.iloc[0],bar.open,rtol=1e-10) and np.isclose(first.price.max(),bar.high,rtol=1e-10)
            assert np.isclose(first.price.min(),bar.low,rtol=1e-10) and np.isclose(first.price.iloc[-1],bar.close,rtol=1e-10)
            cross=first[(first.price>row.upper)|(first.price<row.lower)]
            assert len(cross)>0
            trigger=cross.iloc[0];decision=int(trigger.time);side=1 if trigger.price>row.upper else -1
            if not row['long_known_eligible' if side==1 else 'short_known_eligible']:
                d.at[idx,'status']='first_direction_ineligible';continue
            if decision+5000>=qend:d.at[idx,'status']='expired_before_arrival';continue
            after=x[x.time>=decision+5000]
            if after.empty:d.at[idx,'status']='no_price_reference';continue
            entry=after.iloc[0];execution=int(entry.time);entrybar=execution//M*M
            suffix=after[after.time<entrybar+M];assert len(suffix)>0
            b=minute.loc[entrybar]
            assert suffix.price.max()<=b.high*(1+1e-9) and suffix.price.min()>=b.low*(1-1e-9)
            assert np.isclose(suffix.price.iloc[-1],b.close,rtol=1e-9)
            spec=json.loads(row.long_spec if side==1 else row.short_spec)
            updates={**spec,'observation_id':row.observation_id+'|'+str(side),'status':'verified',
                'archive_sha256':sha,'side':side,'ts':entrybar,'decision_ts':decision,'feature_known_ts':t,
                'signal_close':float(trigger.price),'break_ts':t,'touch_ts':decision,'entry_exec_ts':execution,
                'raw_entry_5s':float(entry.price),'suffix_high':float(suffix.price.max()),
                'suffix_low':float(suffix.price.min()),'suffix_close':float(suffix.price.iloc[-1]),
                'suffix_trade_count':len(suffix),'risk_multiplier':1.}
            opening=float(minute.at[int(row.quarter_start),'open']);ending=float(minute.at[qend-M,'close'])
            body_ret=side*(ending-opening)/opening;beyond=side*(ending-float(spec['level']))>0
            updates.update(large_1pct_label=bool(body_ret>=.01 and beyond),
                           large_halfpct_label=bool(body_ret>=.005 and beyond),completed_body_pct=100*body_ret)
            for key,value in updates.items():d.at[idx,key]=value
            repairs.append({'contract':contract,'day':day,'source':'verified_raw_trades','sha256':sha,
                            'raw_trade_count_in_trigger_minute':len(first),'original_agg_sha256':row.archive_sha256,
                            'trigger_minute':t,'decision_ts':decision,'entry_exec_ts':execution})
    d.to_parquet(path,index=False);meta['statuses']=d.status.value_counts().to_dict();meta['raw_trade_repairs']=repairs
    meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    (HERE/f'原始逐笔修复_{label}.json').write_text(json.dumps({'repairs':repairs,
       'note':'Checksum-verified raw trades replace only missing aggregate-trade event; OHLC and trade count cross-checked against public minute data.'},ensure_ascii=False,indent=2),encoding='utf-8')
    print('RAW_TRADE_REPAIR_COMPLETE',label,len(repairs),'statuses',meta['statuses'],flush=True)
if __name__=='__main__':main()
