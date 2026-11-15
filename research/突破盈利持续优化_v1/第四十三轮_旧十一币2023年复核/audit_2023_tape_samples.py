"""Independently replay selected 2023 public trade sequences and five-second flow."""
import hashlib,io,json,shutil,time
from pathlib import Path
import numpy as np,pandas as pd,psutil,requests
import extract_old11_tapes as run
H=Path(__file__).resolve().parent;M=60_000
def replay(e,tape,lev,fast):
    t=tape.transact_time.to_numpy(np.int64);p=tape.price.to_numpy(float);side=int(e['side'])
    xs=np.flatnonzero((t<e['trigger_minute']+M)&((p>e['upper'])|(p<e['lower'])))
    assert len(xs) and int(t[xs[0]])==int(e['decision_ts']) and (1 if p[xs[0]]>e['upper'] else -1)==side
    first=int(np.searchsorted(t,e['decision_ts']+5000));entryidx=int(np.searchsorted(t,t[first]+5000))
    assert int(t[first])==int(e['entry_exec_ts']) and np.isclose(p[first],e['raw_entry_5s'],rtol=1e-11)
    w=tape[(tape.transact_time>e['decision_ts'])&(tape.transact_time<e['decision_ts']+5000)]
    maker=w.is_buyer_maker.astype(str).str.lower();amount=w.price.to_numpy(float)*w.quantity.to_numpy(float)
    buy=float(amount[maker.eq('false').to_numpy()].sum());sell=float(amount[maker.eq('true').to_numpy()].sum())
    assert len(w)==e['five_count'] and np.isclose(buy,e['buy_notional'],rtol=1e-9,atol=1e-8) and np.isclose(sell,e['sell_notional'],rtol=1e-9,atol=1e-8)
    assert np.isclose(side*(buy-sell)/(buy+sell),e['five_imbalance'],rtol=1e-10)
    raw=float(p[entryidx]);entry=raw*(1+side*.0005);dist=side*(entry-e['stop_price']);assert t[entryidx]<e['quarter_end']
    bad=(dist<=0 or dist>1.5*e['atr'] or side*(entry-e['signal_close'])>.25*e['atr'] or dist/entry+.003>=.5*(1/lev-.01))
    if bad:signal=int(t[entryidx]);reason='filled_beyond_risk_budget'
    else:
        target=entry+side*2*dist;best=(int(e['quarter_end']),3,'quarter_time');inside_start=None
        for ti,price in zip(t[entryidx:],p[entryidx:]):
            ti=int(ti);price=float(price)
            if ti>e['quarter_end']:break
            inside=side*(price-e['level'])<=0
            if inside and inside_start is None:inside_start=ti
            if not inside:inside_start=None
            fails=inside and ti-inside_start>=2000
            choices=[]
            if side*(price-e['stop_price'])<=0:choices.append((ti,0,'stop'))
            if side*(price-target)>=0:choices.append((ti,1,'target'))
            if fast and fails:choices.append((ti,2,'failed_breakout'))
            if choices:best=min([best,*choices])
        signal,_,reason=best
    j=int(np.searchsorted(t,signal+5000));assert j<len(t)
    return {'entry_ts':int(t[entryidx]),'entry_raw':raw,'entry_fill':entry,'exit_signal_ts':signal,
            'exit_ts':int(t[j]),'exit_raw':float(p[j]),'exit_fill':float(p[j])*(1-side*.0005),'reason':reason}
def main():
    src=pd.read_parquet(run.SOURCE).set_index('observation_id');available=[];seen=set()
    for path in sorted(run.WORK.glob('*.json')):
        r=json.loads(path.read_text(encoding='utf-8'))
        if r.get('status')!='verified':continue
        for row in r['rows']:
            if row.get('status')=='qualified' and row['observation_id'] not in seen and row.get('paths') and all(x['status']=='verified' for x in row['paths'].values()):
                seen.add(row['observation_id']);available.append((r,row))
    if len(available)<4:raise ValueError('fewer_than_four_verified_events')
    chosen=[]
    def pick(pred):
        for rec,row in available:
            if row['observation_id'] not in [x[1]['observation_id'] for x in chosen] and pred(row):chosen.append((rec,row));return
    pick(lambda r:r['side']==1);pick(lambda r:r['side']==-1)
    pick(lambda r:any(v.get('reason')=='target' for v in r['paths'].values()))
    pick(lambda r:any(v.get('reason')=='filled_beyond_risk_budget' for v in r['paths'].values()))
    while len(chosen)<4:pick(lambda r:True)
    session=requests.Session();samples=[]
    for rec,row in chosen:
        if shutil.disk_usage(run.ROOT).free<2_200_000_000:raise RuntimeError('disk_headroom')
        while psutil.virtual_memory().available<2_000*1024**2:time.sleep(3)
        e={**src.loc[row['observation_id']].to_dict(),**{k:v for k,v in row.items() if k not in ('paths','prechecks')}};parts=[]
        for a in (x for x in rec['archives'] if x['kind']=='aggTrades'):
            name=f"{e['contract']}-aggTrades-{a['day']}.zip";url=f"https://data.binance.vision/data/futures/um/daily/aggTrades/{e['contract']}/{name}"
            c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
            r=session.get(url,timeout=(15,120));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha==a['sha256']
            for chunk in pd.read_csv(io.BytesIO(r.content),compression='zip',usecols=['agg_trade_id','price','quantity','transact_time','is_buyer_maker'],dtype={'is_buyer_maker':str},chunksize=150_000):
                z=chunk[(chunk.transact_time>=e['trigger_minute'])&(chunk.transact_time<e['quarter_end']+M)]
                if len(z):parts.append(z)
        tape=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        for variant,p in row['paths'].items():
            lev=int(variant.rsplit('_',1)[1].rstrip('x'));other=replay(e,tape,lev,variant.startswith('fast_'))
            for k,v in other.items():
                if isinstance(v,float):assert np.isclose(v,p[k],rtol=1e-11,atol=1e-12),(e['observation_id'],variant,k)
                else:assert v==p[k],(e['observation_id'],variant,k)
        samples.append({'observation_id':row['observation_id'],'side':int(e['side']),'paths_checked':len(row['paths']),
                        'archives':[x for x in rec['archives'] if x['kind']=='aggTrades']})
        print('OLD11_2023_TAPE_SAMPLE',len(samples),'/',len(chosen),flush=True)
    out={'independent_samples':len(samples),'paths_checked':sum(x['paths_checked'] for x in samples),'samples':samples,
         'note':'Public trade prints are price references, not actual fills.'}
    (H/'2023逐笔样本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OLD11_2023_TAPE_SAMPLE_PASS',len(samples),flush=True)
if __name__=='__main__':main()
