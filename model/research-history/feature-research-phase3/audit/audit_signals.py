"""Source and point-in-time audit of matured-event account entry candidates."""
from pathlib import Path
from datetime import datetime, timezone
import importlib.util, json, hashlib, sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent;ACC=ROOT.parent/'account';P2=ROOT.parent.parent/'feature-research-phase2'
sys.path.insert(0,str(ACC));import market_io
spec=importlib.util.spec_from_file_location('phase2_audit_loader',P2/'data_io.py')
p2=importlib.util.module_from_spec(spec);spec.loader.exec_module(p2)
M=60_000;H=60*M;DAY=24*H
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    sig=pd.read_parquet(ACC/'event-signals.parquet')
    sources=[]
    for p in sorted((P2/'feature_outputs/events').glob('*.parquet')):
        f=pd.read_parquet(p); sources.append(f.loc[f.row_id.isin(sig.observation_id)])
    events=pd.concat(sources,ignore_index=True).set_index('row_id')
    assert len(events)==len(sig)==read(ACC/'signal_build.json')['signal_rows'] and events.index.is_unique
    for r in sig.itertuples(index=False):
        e=events.loc[r.observation_id]
        assert r.decision_ts==e.decision_ts==e.t0_open_ts+6*M
        assert r.ts==r.decision_ts+M and r.feature_known_ts<=r.decision_ts
        assert e.decision_valid and e.eligible_decision and not e.quarantined
        assert e.event_status=='measured' and r.side==e.side
        assert r.break_ts==e.t0_open_ts and r.atr==e.A and r.level==e.B
    # Reconstruct hour ranks from the frozen raw-pool clock outputs, not published ranks.
    clocks=[]
    for p in sorted((P2/'feature_outputs/clock').glob('*.parquet')):
        f=pd.read_parquet(p,columns=['decision_ts','symbol','r6','vol24','quote_rvol'])
        clocks.append(f.loc[(f.decision_ts%H)==0])
    h=pd.concat(clocks,ignore_index=True);h['day']=h.decision_ts//DAY*DAY
    pools=[]
    for d in p2.load_daily_pools():
        day=int(pd.Timestamp(d['date'],tz='UTC').timestamp()*1000)
        pools.extend({'day':day,'symbol':x['symbol'],'liquidity_rank':i+1} for i,x in enumerate(d['pool']))
    h=h.merge(pd.DataFrame(pools),on=['day','symbol'],validate='many_to_one')
    quarantine=p2.load_quarantine()
    for symbol,record in quarantine.items():
        h=h.loc[~(h.symbol.eq(symbol)&h.decision_ts.ge(int(record['known_ts'])))].copy()
    h['score']=h.r6/h.vol24.where(h.vol24.gt(0));h=h.loc[h.quote_rvol.ge(1.5)&h.score.notna()&h.score.ne(0)].copy()
    h['side']=np.sign(h.score).astype(int);h['strength']=abs(h.score)
    h=h.sort_values(['decision_ts','side','strength','liquidity_rank','symbol'],ascending=[True,True,False,True,True])
    h=h.groupby(['decision_ts','side']).head(3);h['rank']=h.groupby(['decision_ts','side']).cumcount()+1
    ranks=pd.read_parquet(ACC/'hourly-ranks.parquet')
    a=h.rename(columns={'decision_ts':'hour'}).sort_values(['hour','side','rank'])
    b=ranks.sort_values(['hour','side','rank'])
    ka=set(zip(a.hour,a.symbol,a.side,a['rank']));kb=set(zip(b.hour,b.symbol,b.side,b['rank']))
    assert ka==kb, {'oracle':len(ka),'stored':len(kb),'only_oracle':list(sorted(ka-kb))[:6],'only_stored':list(sorted(kb-ka))[:6]}
    np.testing.assert_allclose(a.score,b.score,rtol=1e-12,atol=1e-12)
    rank_lookup=b.set_index(['hour','symbol','side'])
    for r in sig.itertuples(index=False):
        row=rank_lookup.loc[(r.hour,r.symbol,r.side)]
        assert r.hour==r.decision_ts//H*H and r.rank==row['rank'] and r.liquidity_rank==row.liquidity_rank
        np.testing.assert_allclose(r.score,row.score,rtol=0,atol=0)
    regimes=pd.read_parquet(ACC/'regimes.parquet')
    mapping=p2.load_mapping(); mapped={s:c for s,c in mapping.items() if c}
    assert set(regimes.symbol)==set(mapped)
    from account_market import PoolCorrelationGuard
    correlations=PoolCorrelationGuard()
    assert set(correlations.h.columns)==set(mapped)
    for symbol,contract in mapped.items():
        identity=pd.read_parquet(P2/'feature_outputs/hourly'/f'{symbol}.parquet',columns=['symbol','contract'])
        assert set(identity.symbol)=={symbol} and set(identity.contract)=={contract}
    structural_samples=0;ema_prefixes=[]
    # Window endpoints intentionally span the sample; no outcome based sampling.
    for contract,part in sig.groupby('contract'):
        rows=part.sort_values('decision_ts').iloc[np.unique(np.linspace(0,len(part)-1,min(3,len(part)),dtype=int))]
        for r in rows.itertuples(index=False):
            raw=p2.load_minutes(contract,int(r.break_ts),int(r.decision_ts))
            assert len(raw)==6 and np.array_equal(raw.ts,np.arange(r.break_ts,r.decision_ts,M))
            stop=float(raw.low.min())-.1*r.atr if r.side==1 else float(raw.high.max())+.1*r.atr
            np.testing.assert_allclose(stop,r.stop_price,rtol=0,atol=0)
            np.testing.assert_allclose(float(raw.close.iloc[-1]),r.signal_close,rtol=0,atol=0)
            assert r.side*(r.signal_close-r.level)>0
            structural_samples+=1
    # Direct prefix-only EMA reconstruction: no future rows can enter these calculations.
    for contract in ['AAVEUSDT','RUNEUSDT','TRUMPUSDT','UNIUSDT','BTCUSDT','ETHUSDT','1000PEPEUSDT','1000BONKUSDT','1000SHIBUSDT']:
        mapping=p2.load_mapping();syms=[s for s,c in mapping.items() if c==contract]
        if not syms:continue
        symbol=syms[0];published=regimes.loc[regimes.symbol.eq(symbol)].sort_values('ts').set_index('ts').direction
        if published.empty:continue
        for cutoff in [int(pd.Timestamp('2025-07-01',tz='UTC').timestamp()*1000),int(pd.Timestamp('2026-01-01',tz='UTC').timestamp()*1000)]:
            raw=p2.load_minutes(contract,end_ms=cutoff)
            if raw.empty:continue
            raw=raw.set_index(pd.to_datetime(raw.ts,unit='ms',utc=True))
            raw=raw.reindex(pd.date_range(raw.index.min(),raw.index.max(),freq='min'))
            cols=raw[['open','high','low','close','volume','quote_volume']]
            ok=np.isfinite(cols).all(axis=1)&cols.gt(0).all(axis=1)
            ok &= raw.high.ge(raw[['open','close','low']].max(axis=1))&raw.low.le(raw[['open','close','high']].min(axis=1))
            close=raw.close.where(ok).resample('15min',label='right',closed='left').last()
            good=ok.resample('15min',label='right',closed='left').sum().eq(15)
            close=close.where(good);ema=close.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
            direction=np.select([close.gt(ema)&ema.gt(ema.shift()),close.lt(ema)&ema.lt(ema.shift())],[1,-1],0)
            oracle=pd.Series(direction,index=close.index.as_unit('ms').asi8)
            oracle=oracle.loc[oracle.index<=cutoff]
            common=oracle.index.intersection(published.index)
            assert len(common)>0 and np.array_equal(oracle.loc[common],published.loc[common])
            ema_prefixes.append({'contract':contract,'cutoff_ms':cutoff,'directions_checked':len(common)})
    correction=read(ACC/'ema_source_correction.json')
    archived=ACC/'superseded_market_ema_attempt'
    supplement_effect={}
    for name,info in correction['comparison'].items():
        fixed_ema=ACC/'superseded_symbol_mapping_attempt'/name
        if not fixed_ema.exists():fixed_ema=ACC/name
        assert sha(fixed_ema)==info['new_sha256']
        old=archived/name
        assert old.exists() and sha(old)==info['old_sha256']
        supplement_effect[name]=info
    audit={'completed_utc':datetime.now(timezone.utc).isoformat(),'all_checks_passed':True,
        'candidate_rows_checked':len(sig),'rank_rows_independently_reconstructed':len(ranks),
        'mapped_symbols_in_hourly_and_ema_and_correlation':len(mapped),
        'known_quarantine_applied_before_hourly_top3':True,
        'structural_stop_and_signal_close_samples':structural_samples,'EMA_prefix_checks':ema_prefixes,
        'supplement_scope_correction_verified':True,'supplement_effect':supplement_effect,
        'scope_limit':'All candidate known-times/feature-event identity and ranks, finite stop/EMA prefix oracles; live message availability not recorded.'}
    (ROOT/'signals_independent.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k!='supplement_effect'}))

if __name__=='__main__':main()
