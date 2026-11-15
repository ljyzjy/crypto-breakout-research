"""Re-fetch sample added contracts and independently check hourly aggregation."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;M=60_000;H=60*M
def main():
    sources=json.loads((HERE/'新增备选小时来源.json').read_text(encoding='utf-8'))
    sources=sorted(sources,key=lambda x:(x['year'],x['symbol']));hours=pd.read_parquet(HERE/'前40分钟严格合成小时.parquet')
    picks=sorted(set(np.linspace(0,len(sources)-1,5,dtype=int).tolist()));session=requests.Session();audited=[]
    for i in picks:
        r=sources[i];valid=[x for x in r['archives'] if x['status']=='verified']
        if not valid:continue
        a=valid[len(valid)//2];url='https://data.binance.vision/'+a['key'];c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status()
        sha=c.text.strip().split()[0].lower();response=session.get(url,timeout=(15,100));response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest()==sha==a['sha256']
        d=pd.read_csv(io.BytesIO(response.content),compression='zip');cols=['open','high','low','close','volume','quote_volume']
        assert set(cols+['open_time']).issubset(d.columns) and not d.open_time.duplicated().any()
        valid=np.isfinite(d[cols].to_numpy(float)).all(axis=1)&(d[cols].to_numpy(float)>0).all(axis=1)
        valid&=(d.high>=d[['open','low','close']].max(axis=1))&(d.low<=d[['open','high','close']].min(axis=1))
        d['valid']=valid;d['hour']=d.open_time//H*H
        x=d.sort_values('open_time').groupby('hour').agg(n=('open_time','size'),first=('open_time','first'),last=('open_time','last'),
          valid=('valid','all'),close=('close','last'),quote=('quote_volume','sum'))
        x['valid']=x.valid&(x.n==60)&(x['first']==x.index)&(x['last']==x.index+59*M)
        lo=int(pd.Timestamp(a['month']+'-01',tz='UTC').timestamp()*1000)
        hi=int((pd.Timestamp(a['month']+'-01',tz='UTC')+pd.offsets.MonthBegin(1)).timestamp()*1000)
        t=np.arange(lo,hi,H,dtype=np.int64);x=x.reindex(t)
        y=hours[(hours.year.eq(r['year']))&hours.symbol.eq(r['symbol'])].set_index('open_time').reindex(t)
        good=x.valid.fillna(False).to_numpy(bool);assert np.array_equal(good,y.valid.to_numpy(bool))
        assert np.allclose(x.close.to_numpy(float)[good],y.close.to_numpy(float)[good],rtol=1e-10,atol=1e-10)
        assert np.allclose(x.quote.to_numpy(float)[good],y.quote_volume.to_numpy(float)[good],rtol=1e-9,atol=1e-6)
        audited.append({'year':r['year'],'symbol':r['symbol'],'month':a['month'],'hours':len(t),'valid_hours':int(good.sum()),'sha256':sha})
    out={'sampled_new_archives':len(audited),'samples':audited,
         'note':'Samples verify archive bytes and minute-to-hour aggregation, not historical contract identity or profitability.'}
    (HERE/'新增备选分钟档案抽样核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE34_MINUTE_SAMPLES',len(audited),flush=True)
if __name__=='__main__':main()
