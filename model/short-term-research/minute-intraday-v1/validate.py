from pathlib import Path
import json,subprocess,sys
import pandas as pd
import numpy as np
import psutil
from prepare_data import ROOT,RESEARCH,read,dump,sha,daily_pools
from features import load_contract,make_features
from engine import simulate
from seconds_observer import QuoteExecution

def main():
    subprocess.run([sys.executable,str(ROOT/'test_minute.py')],check=True)
    frozen=read(ROOT/'frozen.json')
    assert all(sha(ROOT/n)==h for n,h in frozen['hashes'].items()),'Frozen source or data changed'
    manifest=read(ROOT/'data-manifest.json')
    assert all(sha(ROOT/r['path'])==r['parquet_sha256'] for r in manifest['records'])
    rows=read(ROOT/'metrics.json');checks={};trades=read(ROOT/'results/main-trades.json')
    for row in rows:
        if not row['valid_for_comparison']:continue
        sid=row['scenario'];t=pd.DataFrame(read(ROOT/f'results/{sid}-trades.json'))
        a=pd.DataFrame(read(ROOT/f'results/{sid}-entries.json'))
        assert abs(row['ledger_error'])<1e-7
        assert t.holding_minutes.between(0,60).all()
        assert t.entry_ts.ge(t.signal_ts).all()
        assert (a.gross_after<=a.known_equity+1e-6).all()
        assert (a.aggregate_planned_loss<=a.known_equity*.005+1e-6).all()
        assert (a.planned_loss<=a.known_equity*a.risk_fraction+1e-6).all()
        assert (a.notional<=a.previous_quote_volume*.001+1e-6).all()
        assert a.slots.le(2).all() and a.day_entries.le(6).all()
        assert (((a.ts//60000+480)%1440)<1320).all()
        for s,g in t.groupby('symbol'):
            g=g.sort_values('entry_ts')
            assert (g.entry_ts.iloc[1:].to_numpy()>=g.exit_ts.iloc[:-1].to_numpy()+3600000).all()
        checks[sid]={'ledger_error':row['ledger_error'],'entries_checked':len(a),'minute_duration_and_risk':True}
    # Actual data prefixes: recompute signals from truncated raw data, not sliced indicators.
    symbols=['BTCUSDT','ETHUSDT','SOLUSDT']
    cutoffs=['2025-02-01','2025-07-01']
    actual_prefix=[]
    for s in symbols:
        c=manifest['mapping'].get(s)
        if not c:continue
        raw=load_contract(c,'klines');full,h=make_features(raw)
        for cut in cutoffs:
            ts=int(pd.Timestamp(cut,tz='UTC').timestamp()*1000)
            short,hs=make_features(raw[raw.ts<ts])
            pd.testing.assert_frame_equal(full[full.ts<=ts].reset_index(drop=True),short[short.ts<=ts].reset_index(drop=True))
            pd.testing.assert_frame_equal(h[h.ts<=ts].reset_index(drop=True),hs[hs.ts<=ts].reset_index(drop=True))
            actual_prefix.append({'symbol':s,'cutoff':cut,'passed':True})
    source=pd.read_parquet(RESEARCH/'coin-lab-v1/pool-daily.parquet')
    daily=read(ROOT/'daily-pools.json')
    prefix,_=daily_pools(source[source.date<pd.Timestamp('2025-03-01',tz='UTC')],'2025-01-01','2025-03-01')
    assert prefix==[r for r in daily if r['date']<='2025-03-01']
    # Replaying only this same strategy on a prefix checks dependence on later executions.
    base=read(ROOT/'protocol.json')['scenarios'][0]
    summary,curve,tt,aa=simulate(base,end='2025-01-31',save=False)
    originals=read(ROOT/'results/main-entries.json');endts=int(pd.Timestamp('2025-02-01',tz='UTC').timestamp()*1000)
    assert aa==[r for r in originals if r['ts']<endts]
    quote=QuoteExecution();quote.update('BTCUSDT',100,101,2,2,1000)
    assert quote.fill('BTCUSDT',1,1,1001,1001) is None
    quote.update('BTCUSDT',100,101,2,2,1002)
    assert quote.fill('BTCUSDT',1,1,1003,1001)['price']==101
    assert quote.fill('BTCUSDT',1,3,1003,1001) is None
    assert quote.fill('BTCUSDT',1,1,4003,1001) is None
    assert quote.trigger('BTCUSDT',1,100,104,1003)=='stop'
    before=read(ROOT/'paper-before.json');kit=RESEARCH.parent
    assert all(sha(kit/p)==h for p,h in before['hashes'].items())
    e=before['processes']['engine'];process=psutil.Process(e['pid'])
    assert process.is_running() and abs(process.create_time()-e['created'])<.01
    assert 'DailyMomentum' in process.cmdline()
    out={'passed':True,'scenarios_valid':sum(r['valid_for_comparison'] for r in rows),'scenarios_total':len(rows),
       'archive_hashes_checked':len(manifest['records']),'checks':checks,'actual_data_prefixes':actual_prefix,
       'daily_pool_prefix':True,'actual_order_prefix':True,'quote_adapter_checks':True,
       'frozen_source_verified':True,'paper_engine_pid':e['pid'],'paper_changed':False,
       'seconds_transport':read(ROOT/'seconds/status.json').get('transport_verified',False),
       'seconds_profitability_validated':False,'utc':pd.Timestamp.now(tz='UTC').isoformat()}
    dump(ROOT/'validation.json',out);print('VALIDATED',json.dumps(out,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
