"""Independently rebuild prior-minute filters and reconcile 5s-entry accounts."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent
M=60_000;Q=15*M
records=pd.read_parquet(HERE/'逐笔首次触价与五秒入场_训练.parquet')
signals=records[records.status.eq('verified')].copy()
assert signals.observation_id.is_unique
checked=0
for (year,contract),g in signals.groupby(['source_year','contract']):
    norm=ROOT/'work'/('breakout_november_2026' if year=='2026' else f'breakout_{year}_11')/'normalized'
    raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','open','high','low','close','volume','quote_volume','trade_count']).set_index('ts')
    assert raw.index.is_unique
    for r in g.itertuples(index=False):
        q=int(r.quarter_start);t=int(r.trigger_minute);k=(t-q)//M;side=int(r.side)
        old=raw.reindex(np.arange(q-20*Q,q,M,dtype=np.int64)).to_numpy(float).reshape(20,15,7)
        prev=raw.reindex(np.arange(q,t,M,dtype=np.int64)).to_numpy(float)
        assert len(prev)==k and k>=1 and np.isfinite(old).all() and np.isfinite(prev).all()
        upper=old[-16:,:,1].max();lower=old[-16:,:,2].min()
        assert np.isclose(upper,r.upper,rtol=1e-10) and np.isclose(lower,r.lower,rtol=1e-10)
        assert (prev[:,1]<=upper).all() and (prev[:,2]>=lower).all()
        high=old[:,:,1].max(axis=1);low=old[:,:,2].min(axis=1);close=old[:,-1,3]
        tr=np.maximum.reduce([high[6:]-low[6:],abs(high[6:]-close[5:-1]),abs(low[6:]-close[5:-1])])
        atr=tr.mean();assert np.isclose(atr,r.atr,rtol=1e-10)
        ratio=prev[:,6].sum()/old[:,:k,6].sum(axis=1).mean()
        body=(prev[-1,3]-prev[0,0])/atr
        assert np.isclose(ratio,r.prior_prefix_ratio,rtol=1e-10) and ratio>=1.5
        assert np.isclose(body,r.prior_body_atr,rtol=1e-10) and side*body>=.1
        stop=prev[-1,2]-.1*atr if side==1 else prev[-1,1]+.1*atr
        assert np.isclose(stop,r.stop_price,rtol=1e-10)
        assert r.feature_known_ts==t and t<=r.decision_ts<t+M and r.entry_exec_ts>=r.decision_ts+5000
        assert r.entry_exec_ts<r.quarter_end and int(r.ts)==int(r.entry_exec_ts)//M*M
        assert side*(r.signal_close-r.level)>0
        opening=float(raw.at[q,'open']);ending=float(raw.at[int(r.quarter_end)-M,'close'])
        body_ret=side*(ending-opening)/opening;beyond=side*(ending-r.level)>0
        assert bool(r.large_1pct_label)==bool(body_ret>=.01 and beyond)
        assert bool(r.large_halfpct_label)==bool(body_ret>=.005 and beyond)
        checked+=1
ticks=signals.set_index('observation_id')
curve_dir=ROOT/'work'/'breakout_profit_research'/'curves'
summaries=list(HERE.glob('*_summary.json'));trade_count=0;max_error=0.;max_dd=0.
for path in summaries:
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(curve_dir/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(trades)==len(entries)==sm['trades']
    assert len(curve)==sm['expected_calendar_minutes']
    eq=np.r_[1000.,curve.equity.to_numpy()];dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    max_dd=max(max_dd,abs(dd-sm['max_drawdown']))
    max_error=max(max_error,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in funding))<1e-7
    for t in trades:
        raw=ticks.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert t['entry_ts']==raw.entry_exec_ts and t['decision_ts']==raw.decision_ts
        assert np.isclose(t['raw_entry'],raw.raw_entry_5s,rtol=1e-11)
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(sm['slippage']+extra)),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert np.isclose(t['target'],t['entry']+side*sm['target_r']*t['initial_price_risk'],rtol=1e-11)
        trade_count+=1
assert max_error<1e-6 and max_dd<1e-8
report={'signal_prior_feature_records_checked':checked,'accounts_checked':len(summaries),'trade_records_checked':trade_count,
        'max_ledger_error_usdt':max_error,'max_drawdown_error_pct_points':max_dd,
        'scope':'All archived signal filters and account records; actual first-cross trade order also checked by separate archive sample and synthetic tests.'}
(HERE/'柱内信号与账户独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TOUCH_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
