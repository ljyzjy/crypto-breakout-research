"""Independent 5-second feature and account reconciliation with tape samples."""
import hashlib,io,json
from pathlib import Path
import numpy as np
import pandas as pd
import requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
sig=pd.read_parquet(HERE.parent/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
sig=sig[sig.status.eq('verified')&sig.source_year.eq('2026')].set_index('observation_id')
ft=pd.read_parquet(HERE/'五秒主动成交特征_2026.parquet').set_index('observation_id')
assert sig.index.is_unique and ft.index.is_unique and set(sig.index)==set(ft.index)
for ix,x in ft.iterrows():
    r=sig.loc[ix]
    if x.status=='verified':
        assert r.decision_ts<x.first_ts<=x.last_ts<r.decision_ts+5000<=r.entry_exec_ts
        assert np.isclose(x.total_notional,x.buy_notional+x.sell_notional,rtol=1e-12)
        assert np.isclose(x.directional_imbalance,r.side*(x.buy_notional-x.sell_notional)/x.total_notional,rtol=1e-12)
        assert -1-1e-12<=x.directional_imbalance<=1+1e-12
accounts=0;trade_count=0
for p in HERE.glob('screen_*_summary.json'):
    sm=json.loads(p.read_text(encoding='utf-8'));stem=p.name.removesuffix('_summary.json')
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    fund=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes']
    assert len(trades)==len(entries)==sm['trades'] and abs(sm['net_pnl']-sum(t['net'] for t in trades))<1e-7
    assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in fund))<1e-7
    eq=np.r_[1000.,curve.equity.to_numpy()];assert abs(np.max(100*(1-eq/np.maximum.accumulate(eq)))-sm['max_drawdown'])<1e-8
    for t in trades:
        r=sig.loc[t['observation_id']];x=ft.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert x.status=='verified' and x['count']>=3 and side*(r.raw_entry_5s-r.level)>0
        assert x.directional_imbalance>=(.1 if '_strong_' in stem else 0.)
        assert t['entry_ts']==r.entry_exec_ts>=r.decision_ts+5000
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(sm['slippage']+extra)),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        trade_count+=1
    accounts+=1
available=ft[ft.status.eq('verified')].sort_index()
chosen=available.iloc[np.unique(np.linspace(0,len(available)-1,min(3,len(available)),dtype=int))]
samples=[]
for ix,x in chosen.iterrows():
    r=sig.loc[ix];name=f'{r.contract}-aggTrades-{r.day}.zip'
    u=f'https://data.binance.vision/data/futures/um/daily/aggTrades/{r.contract}/{name}'
    response=requests.get(u,timeout=(12,120));response.raise_for_status();body=response.content
    assert hashlib.sha256(body).hexdigest()==x.archive_sha256
    parts=[]
    for chunk in pd.read_csv(io.BytesIO(body),compression='zip',usecols=['price','quantity','transact_time','is_buyer_maker'],dtype={'is_buyer_maker':str},chunksize=200_000):
        pick=chunk[chunk.transact_time.gt(r.decision_ts)&chunk.transact_time.lt(r.decision_ts+5000)]
        if len(pick):parts.append(pick)
    tape=pd.concat(parts,ignore_index=True);q=tape.price.to_numpy(float)*tape.quantity.to_numpy(float)
    maker=tape.is_buyer_maker.str.lower();buy=float(q[maker.eq('false').to_numpy()].sum());sell=float(q[maker.eq('true').to_numpy()].sum())
    assert len(tape)==x['count'] and np.isclose(buy,x.buy_notional,rtol=1e-11) and np.isclose(sell,x.sell_notional,rtol=1e-11)
    samples.append({'id':ix,'contract':r.contract,'day':r.day});print('FLOW5_SAMPLE_OK',r.contract,r.day,flush=True)
out={'feature_rows':len(ft),'account_cases':accounts,'trade_records':trade_count,'archive_samples':samples,
     'limit':'Feature uses aggregated public trades; actual order fill and later intraminute sequence remain unverified.'}
(HERE/'五秒主动成交独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('FLOW5_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
