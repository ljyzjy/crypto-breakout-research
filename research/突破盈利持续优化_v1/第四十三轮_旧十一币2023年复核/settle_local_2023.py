"""Settle with checksum-verified local 2023 archives and the verified Feb 24 repair."""
import hashlib,io,json,shutil,time
from pathlib import Path
import numpy as np,pandas as pd,psutil
import settle_2023_engine as engine
import describe_2023_incomplete as diagnosis
H=Path(__file__).resolve().parent;P=H.parent;ROOT=P.parent.parent;OUT=H/'部分批次'
RAW=ROOT/'work'/'breakout_2023_11'/'raw';REPAIR=ROOT/'work'/'breakout_2023_11'/'daily_mark_repair'
NORM=ROOT/'work'/'breakout_2023_11'/'normalized';WORK=ROOT/'work'/'point_in_time_universe33'/'risk_old11_2023_localv1'
SOURCE=json.loads((P/'第二轮_成本空间与即时成交'/'2023公开档案校验清单.json').read_text(encoding='utf-8'))
FIX=json.loads((P/'第二轮_成本空间与即时成交'/'2023日档修复记录.json').read_text(encoding='utf-8'))
RISK_FROZEN=H/'风险来源冻结哈希.json';EXTRA=hashlib.sha256(Path(__file__).read_bytes()+RISK_FROZEN.read_bytes()).hexdigest()
def local_task(spec):
    kind,symbol,month,times=spec
    key=hashlib.sha256((engine.FINGERPRINT+'|'+EXTRA+'|'+kind+'|'+symbol+'|'+month+'|'+','.join(map(str,times))).encode()).hexdigest()
    path=WORK/(key+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    try:
        while psutil.virtual_memory().available<1_100*1024**2:time.sleep(3)
        if shutil.disk_usage(ROOT).free<2_100_000_000:raise RuntimeError('disk_headroom')
        rec=next(x for x in SOURCE['records'] if x['kind']==kind and x['contract']==symbol and x['month']==month and x['status']=='verified')
        name=f'{symbol}-1m-{month}.zip' if kind=='markPriceKlines' else f'{symbol}-fundingRate-{month}.zip'
        local=RAW/kind/symbol/name;body=local.read_bytes();sha=hashlib.sha256(body).hexdigest()
        if sha!=rec['sha256']:raise ValueError('local_raw_hash_mismatch')
        sub=f'{kind}/{symbol}/1m/' if kind=='markPriceKlines' else f'{kind}/{symbol}/'
        url='https://data.binance.vision/data/futures/um/monthly/'+sub+name+'.CHECKSUM'
        c=engine.session().get(url,timeout=(15,50));c.raise_for_status()
        if c.text.strip().split()[0].lower()!=sha:raise ValueError('official_archive_changed')
        d=pd.read_csv(io.BytesIO(body),compression='zip')
        cols=['open_time','open','high','low','close'] if kind=='markPriceKlines' else ['calc_time','funding_interval_hours','last_funding_rate']
        if not set(cols).issubset(d.columns):raise ValueError('source_columns')
        d=d[cols].apply(pd.to_numeric,errors='raise').rename(columns={'open_time':'ts','calc_time':'ts'})
        if not np.isfinite(d.to_numpy(float)).all() or d.ts.duplicated().any():raise ValueError('source_nonfinite_or_duplicate')
        lo=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000);hi=int((pd.Timestamp(month+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        if not d.ts.between(lo,hi-1).all():raise ValueError('source_outside_month')
        repair=None
        if kind=='markPriceKlines':
            if (d.ts%60_000!=0).any() or not (d[['open','high','low','close']]>0).all().all():raise ValueError('invalid_mark')
            if (d.high<d[['open','low','close']].max(axis=1)).any() or (d.low>d[['open','high','close']].min(axis=1)).any():raise ValueError('invalid_mark_ohlc')
            daylo=int(pd.Timestamp('2023-02-24',tz='UTC').timestamp()*1000)
            if month=='2023-02' and any(daylo<=t<daylo+86_400_000 for t in times):
                fx=next(x for x in FIX['records'] if x['contract']==symbol and x['day']=='2023-02-24' and x['status']=='verified_added')
                file=REPAIR/symbol/f'{symbol}-1m-2023-02-24.zip';raw=file.read_bytes();daily_sha=hashlib.sha256(raw).hexdigest()
                if daily_sha!=fx['sha256']:raise ValueError('repair_hash_mismatch')
                url=f'https://data.binance.vision/data/futures/um/daily/markPriceKlines/{symbol}/1m/{symbol}-1m-2023-02-24.zip.CHECKSUM'
                cc=engine.session().get(url,timeout=(15,50));cc.raise_for_status()
                if cc.text.strip().split()[0].lower()!=daily_sha:raise ValueError('official_repair_changed')
                daily=pd.read_csv(io.BytesIO(raw),compression='zip')[['open_time','open','high','low','close']].apply(pd.to_numeric,errors='raise').rename(columns={'open_time':'ts'})
                if len(daily)!=1440 or daily.ts.duplicated().any() or not daily.ts.between(daylo,daylo+86_400_000-1).all():raise ValueError('repair_rows')
                # Add only absent source minutes; disagreements stay errors rather than silently preferring a source.
                overlap=d[d.ts.isin(daily.ts)]
                if len(overlap):
                    y=overlap.merge(daily,on='ts',suffixes=('_month','_day'),validate='one_to_one')
                    for col in ('open','high','low','close'):
                        if not np.allclose(y[col+'_month'],y[col+'_day'],rtol=1e-10,atol=1e-12):raise ValueError('month_repair_disagreement')
                d=pd.concat([d,daily[~daily.ts.isin(d.ts)]],ignore_index=True);repair={'day':'2023-02-24','sha256':daily_sha}
            d=d[d.ts.isin(times)].sort_values('ts')
            norm=pd.read_parquet(NORM/f'{symbol}_markPriceKlines.parquet');norm=norm[norm.ts.isin(times)].sort_values('ts')
            if list(d.ts)!=list(norm.ts):raise ValueError('normalized_mark_time_disagreement')
            if not np.allclose(d[['open','high','low','close']],norm[['open','high','low','close']],rtol=1e-10,atol=1e-12):raise ValueError('normalized_mark_value_disagreement')
        else:
            if (d.funding_interval_hours<=0).any():raise ValueError('funding_interval')
            d=d.sort_values('ts');norm=pd.read_parquet(NORM/f'{symbol}_fundingRate.parquet');norm=norm[norm.ts.between(lo,hi-1)].sort_values('ts')
            if list(d.ts)!=list(norm.ts):raise ValueError('normalized_funding_time_disagreement')
            if not np.allclose(d[['funding_interval_hours','last_funding_rate']],norm[['funding_interval_hours','last_funding_rate']],rtol=1e-10,atol=1e-12):raise ValueError('normalized_funding_value_disagreement')
        out={'kind':kind,'contract':symbol,'month':month,'status':'verified','sha256':sha,'bytes':len(body),
             'local_archive_verified':True,'normalized_agrees':True,'repair':repair,'rows':d.to_dict('records')}
        WORK.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.partial');tmp.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(path)
        return out
    except Exception as e:
        return {'kind':kind,'contract':symbol,'month':month,'status':'error','error':type(e).__name__+':'+str(e)[:150],'rows':[]}
def main():
    synthetic=json.loads((H/'本地风险来源合成核验.json').read_text(encoding='utf-8'));assert synthetic['all_checks_pass']
    frozen=json.loads(RISK_FROZEN.read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()==frozen['plan_sha256']
    for x in frozen['sources'].values():assert hashlib.sha256(Path(x['path']).read_bytes()).hexdigest()==x['sha256']
    old=(P/'第三十三轮_动态池逐笔执行'/'settle_dynamic_paths.py').read_text(encoding='utf-8');new=(H/'settle_2023_engine.py').read_text(encoding='utf-8')
    assert old[:old.index("    end=int(pd.Timestamp('2024-05-01'")]==new[:new.index("    print('OLD11_2023_RISK_COMPLETE'")]
    WORK.mkdir(parents=True,exist_ok=True);engine.HERE=OUT;engine.WORK=WORK;engine.task=local_task
    engine.main()
    if (OUT/'动态池单位筛查完整性.json').exists() and (OUT/'动态池单位收益与风险.parquet').exists():diagnosis.main()
if __name__=='__main__':main()
