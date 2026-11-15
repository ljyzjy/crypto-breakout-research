"""Check one small unresolved raw/aggregate sample against official minute totals."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
CP=ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation';M=60_000
SOURCE=HERE.parent/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet'

def main():
    choices=[]
    for f in CP.glob('*.json'):
        rec=json.loads(f.read_text(encoding='utf-8'))
        if rec.get('status')!='verified':continue
        for row in rec['rows']:
            if row.get('reason')!='five_second_flow_mismatch':continue
            raw=next((a for a in rec['archives'] if a['kind']=='trades'),None)
            if raw:choices.append((raw['bytes'],rec['contract'],rec['day'],row['observation_id'],rec,row))
    assert choices
    _,symbol,day,obs,rec,previous=sorted(choices,key=lambda x:(x[0],x[1],x[2],x[3]))[0]
    e=pd.read_parquet(SOURCE).set_index('observation_id').loc[obs];start=int(e.trigger_minute)
    s=requests.Session();received={};frames={}
    for kind in ('klines','trades'):
        sub=f'klines/{symbol}/1m/{symbol}-1m-{day}.zip' if kind=='klines' else f'trades/{symbol}/{symbol}-trades-{day}.zip'
        url='https://data.binance.vision/data/futures/um/daily/'+sub
        c=s.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
        r=s.get(url,timeout=(15,120));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha
        old=next(a for a in rec['archives'] if a['kind']==kind and a['day']==day);assert old['sha256']==sha
        received[kind]={'sha256':sha,'bytes':len(r.content)}
        frames[kind]=pd.read_csv(io.BytesIO(r.content),compression='zip')
    bars=frames['klines'];raw=frames['trades'];timecol='time' if 'time' in raw.columns else 'transact_time'
    idcol='id' if 'id' in raw.columns else 'trade_id';qtycol='qty' if 'qty' in raw.columns else 'quantity'
    b=bars[bars.open_time.eq(start)];assert len(b)==1;b=b.iloc[0]
    g=raw[raw[timecol].between(start,start+M-1)].sort_values([timecol,idcol],kind='mergesort');assert len(g)
    p=g.price.to_numpy(float);q=g[qtycol].to_numpy(float);maker=g.is_buyer_maker.astype(str).str.lower()
    assert maker.isin(['true','false']).all() and np.isfinite(p).all() and np.isfinite(q).all() and (q>0).all()
    buy=maker.eq('false').to_numpy()
    raw_totals={'open':float(p[0]),'high':float(p.max()),'low':float(p.min()),'close':float(p[-1]),
                'volume':float(q.sum()),'quote_volume':float((p*q).sum()),'count':len(g),
                'taker_buy_volume':float(q[buy].sum()),'taker_buy_quote_volume':float((p[buy]*q[buy]).sum())}
    matches={}
    for field,value in raw_totals.items():
        if field not in b.index:matches[field]={'status':'field_absent'};continue
        official=float(b[field]);matches[field]={'raw':value,'kline':official,
          'close':bool(np.isclose(value,official,rtol=1e-8,atol=1e-10))}
    result={'selection':'smallest completed raw archive among known five-second-flow mismatches',
            'observation_id':obs,'symbol':symbol,'day':day,'source_archives':received,'minute_checks':matches,
            'prior_aggregate_five_second_notional':previous.get('aggregate_flow'),
            'prior_raw_five_second_notional':previous.get('raw_flow'),
            'note':'One data-quality sample only. Count of raw prints and aggregated prints need not coincide; no strategy result.'}
    (HERE/'原始成交与分钟总量单例核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RAW_MINUTE_SAMPLE',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
