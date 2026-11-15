"""Rebuild prior 15m features, 18-pool ranking, five-second inputs and accounts."""
import hashlib,importlib.util,json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parent.parent;M=60_000;Q=15*M
for p in (PARENT,PARENT/'第二轮_成本空间与即时成交'):sys.path.insert(0,str(p))
import flow_research as flow
import train_and_compare as r2
sp=importlib.util.spec_from_file_location('audit_18_configuration',HERE/'generate_18_candidates.py')
config=importlib.util.module_from_spec(sp);sys.modules[sp.name]=config;sp.loader.exec_module(config)
meta=json.loads((HERE/'十八币逐笔核验清单.json').read_text(encoding='utf-8'))
fatal={'archive_error','no_trigger_data','ohlc_trade_mismatch','no_price_reference','no_price_before_candle_end',
       'minute_archive_mismatch','missing_completed_candle'}
assert not meta['archive_errors'] and not any(meta['statuses'].get(k,0) for k in fatal)
data=pd.read_parquet(HERE/'十八币首次触价五秒成交.parquet');data=data[data.status.eq('verified')].copy()
assert data.observation_id.is_unique and not data.duplicated(['symbol','quarter_start']).any()
assert (data.entry_exec_ts>=data.decision_ts+5000).all() and (data.entry_exec_ts<data.quarter_end).all()
old=pd.read_parquet(PARENT/'第二十六轮_全时段五秒主动成交'/'全时段五秒特征候选.parquet').set_index('observation_id')
reused=data[data.tape_source.eq('reused')]
for r in reused.itertuples(index=False):
    q=old.loc[r.observation_id]
    for k in ('decision_ts','entry_exec_ts','raw_entry_5s','suffix_high','suffix_low','suffix_close','five_count','five_imbalance'):
        assert np.isclose(getattr(r,k),q[k],rtol=1e-11,atol=1e-12),(r.observation_id,k)
    assert r.archive_sha256==q.archive_sha256==r.flow_archive_sha
checked=0;rankchecked=0
for year in (2024,2026):
    r2.configure(year);market=flow.forward.FixedMarket();guard=flow.forward.FixedGuard(market)
    sub=data[data.source_year.eq(str(year))]
    folder='breakout_2024_expanded18' if year==2024 else 'breakout_november_2026'
    for contract,g in sub.groupby('contract'):
        raw=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{contract}_klines.parquet',
             columns=['ts','open','high','low','close','volume','quote_volume','trade_count']).set_index('ts')
        assert raw.index.is_unique
        for r in g.itertuples(index=False):
            q=int(r.quarter_start);t=int(r.trigger_minute);side=int(r.side)
            old20=raw.reindex(np.arange(q-20*Q,q,M,dtype=np.int64)).to_numpy(float).reshape(20,15,7)
            assert np.isfinite(old20).all()
            upper=old20[-16:,:,1].max();lower=old20[-16:,:,2].min()
            high=old20[:,:,1].max(axis=1);low=old20[:,:,2].min(axis=1);close=old20[:,-1,3]
            atr=np.maximum.reduce([high[6:]-low[6:],abs(high[6:]-close[5:-1]),abs(low[6:]-close[5:-1])]).mean()
            assert np.isclose(upper,r.upper,rtol=1e-10) and np.isclose(lower,r.lower,rtol=1e-10) and np.isclose(atr,r.atr,rtol=1e-10)
            assert np.isclose(r.level,upper if side==1 else lower,rtol=1e-10) and side*(r.signal_close-r.level)>0
            if r.cohort=='opening':
                first=raw.reindex(np.arange(q-21*Q,q-20*Q,M,dtype=np.int64)).to_numpy(float)
                previous=np.vstack([first,old20.reshape(-1,7)]).reshape(21,15,7)
                pace=previous[-1,:,6].sum()/previous[:-1,:,6].sum(axis=1).mean()
                body=(previous[-1,-1,3]-previous[-1,0,0])/atr
                stop=previous[-1,-1,2]-.1*atr if side==1 else previous[-1,-1,1]+.1*atr
                assert t==q and side*body>=.1
            else:
                k=(t-q)//M;prefix=raw.reindex(np.arange(q,t,M,dtype=np.int64)).to_numpy(float)
                assert k>=1 and len(prefix)==k and np.isfinite(prefix).all()
                pace=prefix[:,6].sum()/old20[:,:k,6].sum(axis=1).mean()
                body=(prefix[-1,3]-prefix[0,0])/atr
                stop=prefix[-1,2]-.1*atr if side==1 else prefix[-1,1]+.1*atr
                assert pace>=1.5 and side*body>=.1 and (prefix[:,1]<=upper).all() and (prefix[:,2]>=lower).all()
            assert np.isclose(pace,r.prior_prefix_ratio,rtol=1e-10) and np.isclose(body,r.prior_body_atr,rtol=1e-10)
            assert np.isclose(stop,r.stop_price,rtol=1e-10) and r.feature_known_ts==t<=r.decision_ts<t+M
            assert guard.eligible(r.symbol,side,t)
            rank=guard.rank(r.symbol,side,t);assert rank['rank']==r.rank and np.isclose(rank['score'],r.score) and np.isclose(rank['rvol'],r.rvol)
            rankchecked+=1
            if r.five_status=='verified':
                assert r.first_ts>r.decision_ts and r.last_ts<r.window_end<=r.entry_exec_ts
                assert np.isclose(r.total_notional,r.buy_notional+r.sell_notional,rtol=1e-11)
                assert np.isclose(r.five_imbalance,side*(r.buy_notional-r.sell_notional)/r.total_notional,rtol=1e-11,atol=1e-12)
            checked+=1
    del market,guard
choice=json.loads((HERE/'十八币冻结决定.json').read_text(encoding='utf-8'))
assert choice['plan_sha256']==hashlib.sha256((HERE/'冻结研究计划.json').read_bytes()).hexdigest()
assert choice['training_sha256']==hashlib.sha256((HERE/'十八币训练候选.json').read_bytes()).hexdigest()
train=json.loads((HERE/'十八币训练候选.json').read_text(encoding='utf-8'))
viable=[s for s in train if s['valid_for_comparison'] and s['trades']>=30]
passed=[s for s in viable if s['net_win_rate_pct'] is not None and s['net_win_rate_pct']>=60 and s['net_pnl']>0 and s['profit_factor'] is not None and s['profit_factor']>1]
assert bool(passed)==choice['training_passed']
if viable:assert max(passed or viable,key=lambda x:x['net_pnl'])['run_id']==choice['selected']
idx=data.set_index('observation_id');near=lambda a,b:math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
accounts=records=partials=0
for path in HERE.glob('*_summary.json'):
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    ts=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    es=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    fs=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(ts)==len(es)==sm['trades']
    assert near(sm['net_pnl'],sum(t['net'] for t in ts)) and near(sum(t['funding'] for t in ts),sum(f['actual_charge'] for f in fs))
    eq=np.r_[1000.,curve.equity.to_numpy()];assert near(np.max(100*(1-eq/np.maximum.accumulate(eq))),sm['max_drawdown'])
    for t in ts:
        r=idx.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert r.five_status=='verified' and r.five_count>=3 and r.five_imbalance>=.1
        assert side*(r.raw_entry_5s-r.level)>0 and t['entry_ts']==r.entry_exec_ts
        q=t['qty'];part=t['partial_qty'];end=q-part;fee=sm['fee'];slip=sm['slippage']
        assert near(t['entry_fee'],q*t['entry']*fee) and near(t['entry'],t['raw_entry']*(1+side*slip))
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert near(t['final_fill'],t['final_raw_exit']*(1-side*(slip+extra)))
        assert near(t['final_exit_fee'],end*t['final_fill']*fee+t['liquidation_penalty'])
        if part:
            partials+=1;assert near(part,.5*q) and t['partial_ts']>=t['partial_known_ts']+M
            assert near(t['partial_fill'],t['partial_raw_exit']*(1-side*slip)) and near(t['partial_exit_fee'],part*t['partial_fill']*fee)
            assert near(t['stop'],t['entry']+side*.25*t['initial_price_risk'])
        expected=side*(part*(t['partial_fill']-t['entry'])+end*(t['final_fill']-t['entry']))-t['entry_fee']-t['exit_fee']-t['funding']
        assert near(expected,t['net']) and near(t['exit_fee'],t['partial_exit_fee']+t['final_exit_fee'])
    accounts+=1;records+=len(ts)
out={'signal_feature_rows':checked,'rank_checks':rankchecked,'reused_event_checks':len(reused),
     'accounts_checked':accounts,'trade_records_checked':records,'partial_exits_checked':partials,
     'training_selection_reproduced':True,'scope':'Prior 15m features, 18-pool causal ranking, 5s flow, cost, partial exits and account ledger.'}
(HERE/'十八币信号与账户独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXPANDED18_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
