"""Independently replay selected public-tape samples, including UTC rollover."""
import hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,requests
HERE=Path(__file__).resolve().parent
M=60_000

def independent_replay(e,tape):
    t=tape.transact_time.to_numpy(np.int64);p=tape.price.to_numpy(float)
    cross=np.flatnonzero((t<e.trigger_minute+M)&((p>e.upper)|(p<e.lower)))
    assert len(cross) and t[cross[0]]==e.decision_ts
    assert (1 if p[cross[0]]>e.upper else -1)==e.side
    ref=np.searchsorted(t,e.decision_ts+5000);fill=np.searchsorted(t,t[ref]+5000)
    assert t[ref]==e.entry_exec_ts and np.isclose(p[ref],e.raw_entry_5s,rtol=1e-11)
    side=int(e.side);raw=float(p[fill]);entry=raw*(1+side*.0005);distance=side*(entry-e.stop_price)
    assert t[fill]<e.quarter_end
    invalid=(distance<=0 or distance>1.5*e.atr or side*(entry-e.signal_close)>.25*e.atr or
             distance/entry+.002+.0005+.0005>=.5*(1/20-.005-.005))
    names=['normal_1r','fast_1r','normal_2r','fast_2r']
    outcome={n:(int(t[fill]),0,'filled_beyond_risk_budget') if invalid else (int(e.quarter_end),3,'quarter_time') for n in names}
    inside_start=None
    if not invalid:
        # One pass over ordered prints; within the same millisecond the agreed
        # stop/target/failure priority resolves ambiguous first signals.
        for timestamp,price in zip(t[fill:],p[fill:]):
            timestamp=int(timestamp);price=float(price)
            if timestamp>e.quarter_end:break
            inside=side*(price-e.level)<=0
            if inside and inside_start is None:inside_start=timestamp
            if not inside:inside_start=None
            failed=inside and timestamp-inside_start>=2000
            for n in names:
                old=outcome[n]
                if timestamp>old[0]:continue
                candidates=[]
                if side*(price-e.stop_price)<=0:candidates.append((timestamp,0,'stop'))
                target_r=1 if n.endswith('1r') else 2
                if side*(price-(entry+side*target_r*distance))>=0:candidates.append((timestamp,1,'target'))
                if n.startswith('fast') and failed:candidates.append((timestamp,2,'failed_breakout'))
                if candidates:outcome[n]=min([old,*candidates])
    paths={}
    for name,(signal,priority,reason) in outcome.items():
        j=np.searchsorted(t,signal+5000);assert j<len(t)
        paths[name]={'entry_ts':int(t[fill]),'entry_raw':raw,'entry_fill':entry,'exit_signal_ts':signal,
                     'exit_ts':int(t[j]),'exit_raw':float(p[j]),'exit_fill':float(p[j])*(1-side*.0005),'reason':reason}
    return paths

def main():
    d=pd.read_parquet(HERE/'事前条件通过候选.parquet')
    p=pd.read_parquet(HERE/'秒级路径与延迟参考.parquet')
    fast=p[p.variant.eq('fast_1r')][['observation_id','reason']]
    z=d.merge(fast,on='observation_id',validate='one_to_one').sort_values(['source_year','decision_ts','symbol'])
    picks=[]
    def pick(frame):
        if len(frame):
            for row in frame.itertuples(index=False):
                if row.observation_id not in picks:
                    picks.append(row.observation_id);return
    pick(z[z.needs_next]);pick(z[(z.side.eq(-1))&z.source_year.eq('2024')]);pick(z[(z.side.eq(1))&z.source_year.eq('2026')])
    pick(z[z.reason.eq('failed_breakout')]);pick(z[z.reason.eq('target')]);pick(z[z.reason.eq('filled_beyond_risk_budget')])
    if len(picks)<4:
        for _ in range(4-len(picks)):pick(z)
    audited=[];session=requests.Session()
    for obs in picks:
        e=d.set_index('observation_id').loc[obs];parts=[];archives=[]
        dates=[e.day]
        if e.needs_next:dates.append((pd.Timestamp(e.day,tz='UTC')+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        for day in dates:
            name=f'{e.contract}-aggTrades-{day}.zip'
            url=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{e.contract}/{name}'
            a=session.get(url+'.CHECKSUM',timeout=(15,60));a.raise_for_status();sha=a.text.strip().split()[0].lower()
            a=session.get(url,timeout=(15,120));a.raise_for_status();assert hashlib.sha256(a.content).hexdigest()==sha
            if day==e.day:assert sha==e.archive_sha256
            archives.append({'day':day,'sha256':sha})
            for chunk in pd.read_csv(io.BytesIO(a.content),compression='zip',usecols=['agg_trade_id','price','transact_time'],chunksize=150_000):
                c=chunk[(chunk.transact_time>=e.trigger_minute)&(chunk.transact_time<e.quarter_end+60_000)]
                if len(c):parts.append(c)
        tape=pd.concat(parts,ignore_index=True).sort_values(['transact_time','agg_trade_id'],kind='mergesort')
        independent=independent_replay(e,tape);expected=p[p.observation_id.eq(obs)].set_index('variant')
        for name,vals in independent.items():
            for key,v in vals.items():
                stored=expected.loc[name,key]
                if isinstance(v,float):assert np.isclose(v,float(stored),rtol=1e-11,atol=1e-12),(obs,name,key)
                else:assert v==stored,(obs,name,key,v,stored)
        audited.append({'observation_id':obs,'contract':e.contract,'side':int(e.side),'archives':archives,
                        'checked_variants':len(independent),'crosses_utc_day':bool(e.needs_next),
                        'fast_1r_reason':independent['fast_1r']['reason']})
        print('SECONDS29_SAMPLE',len(audited),'/',len(picks),obs,flush=True)
    out={'independently_replayed_samples':len(audited),'paths':sum(x['checked_variants'] for x in audited),
         'samples':audited,'note':'Independent code; official public archive checksum verified. Public prints are not actual order fills.'}
    (HERE/'秒级公开逐笔样本复核.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SECONDS29_SAMPLE_AUDIT_PASS',len(audited),flush=True)
if __name__=='__main__':main()
