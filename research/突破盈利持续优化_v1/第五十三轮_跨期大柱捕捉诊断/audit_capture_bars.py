"""Check sampled minute-aggregated labels against official 15-minute archives."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np,pandas as pd,requests
H=Path(__file__).resolve().parent;I=H/'冻结输入';M=60_000;Q=15*M
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume','ignore']
def main():
    labels=pd.read_parquet(H/'跨期事后大柱标签.parquet');sources=json.loads((I/'minute_sources.json').read_text(encoding='utf-8'))['sources']
    session=requests.Session();checked=[];archives=[]
    for year in ('2024','2026'):
        valid=labels[labels.source_year.eq(year)&labels.status.eq('verified')].sort_values(['contract','quarter_start'])
        symbols=sorted(valid.contract.unique());assert len(symbols)>=2
        for sym in (symbols[0],symbols[-1]):
            g=valid[valid.contract.eq(sym)].sort_values('quarter_start');target=g.iloc[len(g)//2];q=int(target.quarter_start)
            needed=list(range(q-16*Q,q+Q,Q));months=sorted({pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m') for t in needed});original=[]
            for month in months:
                url=f'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/15m/{sym}-15m-{month}.zip'
                c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();expected=c.text.strip().split()[0].lower()
                response=session.get(url,timeout=(15,90));response.raise_for_status();assert hashlib.sha256(response.content).hexdigest()==expected
                with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                    names=z.namelist();assert len(names)==1;raw=z.read(names[0]);header=raw.splitlines()[0].decode('utf-8-sig').lower().startswith('open_time,')
                bars=pd.read_csv(io.BytesIO(raw),header=0 if header else None,names=None if header else COLS)
                original.append(bars[bars.open_time.isin(needed)]);archives.append({'year':year,'contract':sym,'month':month,'sha256':expected})
            original=pd.concat(original,ignore_index=True).set_index('open_time');assert original.index.is_unique
            item=sources[f'{year}_{sym}'];path=Path(item['path'])
            with path.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
            assert actual==item['sha256'];minute=pd.read_parquet(path,columns=['ts','open','high','low','close','volume','trade_count']).set_index('ts')
            for t in needed:
                m=minute.reindex(range(t,t+Q,M));assert len(m)==15 and m.notna().all().all() and t in original.index
                raw=original.loc[t];agg=[m.open.iloc[0],m.high.max(),m.low.min(),m.close.iloc[-1],m.volume.sum()]
                ref=[raw['open'],raw['high'],raw['low'],raw['close'],raw['volume']]
                assert np.allclose(agg,ref,rtol=1e-9,atol=1e-12),(year,sym,t)
                assert int(m.trade_count.sum())==int(raw['count'])
                if t==q:
                    assert np.allclose(agg[:4],[target.open,target.high,target.low,target.close],rtol=1e-9,atol=1e-12)
                    assert int(raw['count'])==int(target.trade_count)
            checked.append({'year':year,'contract':sym,'quarter_start':q,'current_and_prior_quarters_checked':len(needed)})
            print('CAPTURE53_BAR_SAMPLE',len(checked),'/4',flush=True)
    out={'all_checks_pass':True,'sample_candidates':len(checked),'quarter_bars_checked':sum(x['current_and_prior_quarters_checked'] for x in checked),
         'samples':checked,'archives':archives,'note':'Same-exchange 1m and 15m consistency; not independent feeds.'}
    (H/'跨期大柱行情样本核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE53_BAR_AUDIT_PASS',len(checked),flush=True)
if __name__=='__main__':main()
