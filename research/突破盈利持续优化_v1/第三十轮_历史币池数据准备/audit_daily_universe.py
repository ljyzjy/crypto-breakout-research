"""Rebuild all previous-30-day ranks, and independently re-fetch sample archives."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
from download_rank_daily import FINGERPRINT,DAY,WORK
HERE=Path(__file__).resolve().parent
def main():
    index=pd.read_parquet(HERE/'历史日线月档索引.parquet');daily=pd.read_parquet(HERE/'公开日线已校验成交额.parquet')
    ranked=pd.read_parquet(HERE/'历史动态20币候选_仅数据排名.parquet')
    meta=json.loads((HERE/'历史动态币池数据质量.json').read_text(encoding='utf-8'))
    errors={(x['symbol'],x['month']) for x in meta['archive_errors']};manifest=[];rows=0
    for r in index.to_dict('records'):
        ident=hashlib.sha256((FINGERPRINT+'|'+r['key']+'|'+str(r['size'])+'|'+r['last_modified']).encode()).hexdigest()
        path=WORK/(ident+'.json')
        if path.exists():
            z=json.loads(path.read_text(encoding='utf-8'))
            assert z['status']=='verified' and z['symbol']==r['symbol'] and z['month']==r['month'] and z['key']==r['key']
            rows+=len(z['rows']);manifest.append({'symbol':r['symbol'],'month':r['month'],'key':r['key'],'status':'verified',
                                                    'sha256':z['sha256'],'row_count':len(z['rows']),'checkpoint':str(path)})
        else:
            assert (r['symbol'],r['month']) in errors
            manifest.append({'symbol':r['symbol'],'month':r['month'],'key':r['key'],'status':'error','sha256':None,'row_count':0,'checkpoint':None})
    man=pd.DataFrame(manifest);man.to_parquet(HERE/'历史日线档案核验清单.parquet',index=False)
    assert rows==len(daily) and int(man.status.eq('verified').sum())==meta['verified_archives']
    assert not daily.duplicated(['symbol','open_time']).any()
    assert (daily.close_time==daily.open_time+DAY-1).all()
    # Independent cross-sectional reconstruction: every calendar day explicitly
    # takes the 30 known previous days and sorts the whole eligible universe.
    price=daily.copy();price.loc[~price.valid_for_ranking,'quote_volume']=np.nan
    wide=price.pivot(index='open_time',columns='symbol',values='quote_volume').sort_index()
    days=sorted(ranked.day.unique());checks=0;total=0;max_relative=0.
    for day in days:
        now=int(pd.Timestamp(day,tz='UTC').timestamp()*1000)
        previous=wide.reindex(np.arange(now-30*DAY,now,DAY,dtype=np.int64))
        eligible=previous.notna().all(axis=0);sums=previous.loc[:,eligible].sum(axis=0)
        expected=pd.DataFrame({'symbol':sums.index,'q':sums.to_numpy(float)}).sort_values(['q','symbol'],ascending=[False,True]).head(20)
        actual=ranked[ranked.day.eq(day)].sort_values('rank')
        assert expected.symbol.tolist()==actual.symbol.tolist(),('rank mismatch',day)
        assert actual.eligible_symbols_that_day.eq(int(eligible.sum())).all()
        dif=np.abs(expected.q.to_numpy()-actual.past_30d_quote.to_numpy())
        rel=dif/np.maximum(1.,np.abs(expected.q.to_numpy()))
        if len(rel):max_relative=max(max_relative,float(rel.max()))
        assert not len(rel) or rel.max()<1e-11
        assert actual['rank'].tolist()==list(range(1,len(actual)+1));checks+=1;total+=len(actual)
    # Re-fetch diverse archives directly; checksums and CSV fields are checked
    # separately from the downloader and the cached normalized rows.
    pool=man[man.status.eq('verified')].sort_values(['month','symbol']).reset_index(drop=True)
    picks=[]
    for symbol,month in [('BTCUSDT','2023-12'),('BTCUSDT','2024-06'),('BTCUSDT','2026-04'),('BTCUSDT','2026-07')]:
        part=pool[pool.symbol.eq(symbol)&pool.month.eq(month)]
        if len(part):picks.append(part.iloc[0])
    for frac in (.13,.37,.63,.87):
        if len(pool):picks.append(pool.iloc[int((len(pool)-1)*frac)])
    samples=[];seen=set();session=requests.Session()
    for r in picks:
        if (r.symbol,r.month) in seen:continue
        seen.add((r.symbol,r.month));url='https://data.binance.vision/'+r.key
        c=session.get(url+'.CHECKSUM',timeout=(15,45));c.raise_for_status();official=c.text.strip().split()[0].lower()
        a=session.get(url,timeout=(15,90));a.raise_for_status()
        assert hashlib.sha256(a.content).hexdigest()==official==r.sha256
        raw=pd.read_csv(io.BytesIO(a.content),compression='zip')
        assert {'open_time','close_time','quote_volume'}.issubset(raw.columns)
        observed=daily[(daily.symbol.eq(r.symbol))&(pd.to_datetime(daily.open_time,unit='ms',utc=True).dt.strftime('%Y-%m').eq(r.month))].sort_values('open_time')
        raw=raw.sort_values('open_time');assert len(raw)==len(observed)==r.row_count
        assert np.array_equal(raw.open_time.to_numpy(np.int64),observed.open_time.to_numpy(np.int64))
        assert np.array_equal(raw.close_time.to_numpy(np.int64),observed.close_time.to_numpy(np.int64))
        assert np.allclose(raw.quote_volume.to_numpy(float),observed.quote_volume.to_numpy(float),rtol=1e-12,atol=1e-12)
        samples.append({'symbol':r.symbol,'month':r.month,'sha256':official,'rows':len(raw)})
    out={'all_archives_manifested':len(man),'verified_archives':int(man.status.eq('verified').sum()),
         'recorded_error_archives':len(errors),'daily_rows':len(daily),'ranked_days_independently_reconstructed':checks,
         'ranked_rows_independently_reconstructed':total,'maximum_relative_quote_error':max_relative,
         'public_archive_samples':samples,'no_same_day_volume':True,'missing_day_excluded':True,
         'note':'Archive availability and a volume rank do not establish historical trading eligibility or profitability.'}
    (HERE/'历史动态币池独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE30_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
