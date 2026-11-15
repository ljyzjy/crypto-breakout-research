"""Independently replay selected P10/P15 paths from checksum-verified public prints."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;WORK=ROOT/'work'/'follow35'/'tape';M=60_000
def independent(e,tape,leverage,fast):
    t=tape.transact_time.to_numpy(np.int64);p=tape.price.to_numpy(float);side=int(e.side)
    x=np.flatnonzero((t<e.trigger_minute+M)&((p>e.upper)|(p<e.lower)));assert len(x) and t[x[0]]==e.decision_ts
    i5=np.searchsorted(t,e.decision_ts+5000);i10=np.searchsorted(t,t[i5]+5000);entry_idx=np.searchsorted(t,t[i10]+5000)
    assert t[i5]==e.entry_exec_ts and t[i10]==e.second_ref_ts and np.isclose(p[i10],e.second_ref_price,rtol=1e-11)
    assert side*(p[i10]-p[i5])>0
    raw=float(p[entry_idx]);entry=raw*(1+side*.0005);dist=side*(entry-e.stop_price)
    invalid=(dist<=0 or dist>1.5*e.atr or side*(entry-e.signal_close)>.25*e.atr or
             dist/entry+.003>=.5*(1/leverage-.01))
    if invalid:signal=int(t[entry_idx]);reason='filled_beyond_risk_budget'
    else:
        target=entry+side*2*dist;chosen=(int(e.quarter_end),3,'quarter_time');inside_start=None
        for timestamp,price in zip(t[entry_idx:],p[entry_idx:]):
            timestamp=int(timestamp);price=float(price)
            if timestamp>e.quarter_end:break
            inside=side*(price-e.level)<=0
            if inside and inside_start is None:inside_start=timestamp
            if not inside:inside_start=None
            failure=inside and timestamp-inside_start>=2000
            if timestamp>chosen[0]:continue
            c=[]
            if side*(price-e.stop_price)<=0:c.append((timestamp,0,'stop'))
            if side*(price-target)>=0:c.append((timestamp,1,'target'))
            if fast and failure:c.append((timestamp,2,'failed_breakout'))
            if c:chosen=min([chosen,*c])
        signal,_,reason=chosen
    j=np.searchsorted(t,signal+5000);assert j<len(t)
    return {'entry_ts':int(t[entry_idx]),'entry_raw':raw,'entry_fill':entry,'exit_signal_ts':signal,
            'exit_ts':int(t[j]),'exit_raw':float(p[j]),'exit_fill':float(p[j])*(1-side*.0005),'reason':reason}
def main():
    cand=pd.read_parquet(HERE/'二次跟随事前候选.parquet').set_index('observation_id');complete=[];seen=set()
    for path in sorted(WORK.glob('*.json')):
        r=json.loads(path.read_text(encoding='utf-8'))
        if r.get('status')!='verified':continue
        for row in r['rows']:
            if row['status']=='verified' and row['observation_id'] not in seen:
                seen.add(row['observation_id']);complete.append((r,row))
    if len(complete)<4:raise ValueError('fewer_than_four_completed_samples')
    chosen=[]
    def pick(predicate):
        for rec,row in complete:
            if row['observation_id'] not in [x[1]['observation_id'] for x in chosen] and predicate(cand.loc[row['observation_id']],row):chosen.append((rec,row));return
    pick(lambda e,r:int(e.side)==1);pick(lambda e,r:int(e.side)==-1)
    pick(lambda e,r:any(x.get('reason')=='target' for x in r['paths'].values()))
    pick(lambda e,r:any(x.get('reason')=='failed_breakout' for x in r['paths'].values()))
    pick(lambda e,r:any(x.get('reason')=='filled_beyond_risk_budget' for x in r['paths'].values()))
    while len(chosen)<4:pick(lambda e,r:True)
    results=[];session=requests.Session()
    for rec,row in chosen:
        e=cand.loc[row['observation_id']];parts=[]
        for a in rec['archives']:
            name=f"{e.contract}-aggTrades-{a['day']}.zip";url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{e.contract}/{name}'
            c=session.get(url+'.CHECKSUM',timeout=(15,50));c.raise_for_status();sha=c.text.strip().split()[0].lower()
            r=session.get(url,timeout=(15,120));r.raise_for_status();assert hashlib.sha256(r.content).hexdigest()==sha==a['sha256']
            for chunk in pd.read_csv(io.BytesIO(r.content),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=150_000):
                z=chunk[(chunk.transact_time>=e.trigger_minute)&(chunk.transact_time<e.quarter_end+M)]
                if len(z):parts.append(z)
        tape=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        for variant,expected in row['paths'].items():
            lev=int(variant.rsplit('_',1)[1].rstrip('x'));actual=independent(e,tape,lev,variant.startswith('fast_'))
            for k,v in actual.items():
                if isinstance(v,float):assert np.isclose(v,expected[k],rtol=1e-11,atol=1e-12),(row['observation_id'],variant,k)
                else:assert v==expected[k],(row['observation_id'],variant,k)
        results.append({'observation_id':row['observation_id'],'contract':e.contract,'side':int(e.side),
                        'variants_checked':len(row['paths']),'archives':rec['archives']})
        print('FOLLOW35_SAMPLE',len(results),'/',len(chosen),flush=True)
    out={'sample_events':len(results),'variant_paths':sum(x['variants_checked'] for x in results),'samples':results,
         'note':'Independent tick replay; public prints are hypothetical price references, not actual fills.'}
    (HERE/'二次跟随逐笔样本独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FOLLOW35_SAMPLE_AUDIT_PASS',len(results),flush=True)
if __name__=='__main__':main()
