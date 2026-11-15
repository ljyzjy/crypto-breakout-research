"""Independent reconstruction of prior-minute features and account ledger."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent;M=60_000;Q=15*M
data=pd.read_parquet(HERE.parent/'第十四轮_首分钟逐笔突破'/'首分钟首次触价与五秒参考.parquet')
signals=data[data.status.eq('verified')].copy();assert signals.observation_id.is_unique
count=0
for (year,contract),g in signals.groupby(['source_year','contract']):
    norm=ROOT/'work'/('breakout_november_2026' if year=='2026' else f'breakout_{year}_11')/'normalized'
    raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','open','high','low','close','volume','quote_volume','trade_count']).set_index('ts')
    assert raw.index.is_unique
    for r in g.itertuples(index=False):
        q=int(r.quarter_start);side=int(r.side)
        old=raw.reindex(np.arange(q-21*Q,q,M,dtype=np.int64)).to_numpy(float).reshape(21,15,7)
        assert np.isfinite(old).all()
        last20=old[-20:];upper=last20[-16:,:,1].max();lower=last20[-16:,:,2].min()
        assert np.isclose(upper,r.upper,rtol=1e-10) and np.isclose(lower,r.lower,rtol=1e-10)
        high=last20[:,:,1].max(axis=1);low=last20[:,:,2].min(axis=1);close=last20[:,-1,3]
        atr=np.maximum.reduce([high[6:]-low[6:],abs(high[6:]-close[5:-1]),abs(low[6:]-close[5:-1])]).mean()
        ratio=old[-1,:,6].sum()/old[:-1,:,6].sum(axis=1).mean()
        body=(old[-1,-1,3]-old[-1,0,0])/atr
        stop=old[-1,-1,2]-.1*atr if side==1 else old[-1,-1,1]+.1*atr
        assert np.isclose(atr,r.atr,rtol=1e-10) and np.isclose(ratio,r.prior_prefix_ratio,rtol=1e-10)
        assert np.isclose(body,r.prior_body_atr,rtol=1e-10) and side*body>=.1
        assert np.isclose(stop,r.stop_price,rtol=1e-10)
        assert q==r.feature_known_ts==r.trigger_minute and q<=r.decision_ts<q+M
        assert r.entry_exec_ts>=r.decision_ts+5000 and r.entry_exec_ts<r.quarter_end
        assert side*(r.signal_close-r.level)>0
        opening=float(raw.at[q,'open']);closing=float(raw.at[int(r.quarter_end)-M,'close'])
        result=side*(closing-opening)/opening;beyond=side*(closing-r.level)>0
        assert bool(r.large_1pct_label)==bool(result>=.01 and beyond)
        count+=1
ticks=signals.set_index('observation_id');summaries=list(HERE.glob('train_*_summary.json'));trade_count=0;opens={}
for path in summaries:
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(ROOT/'work'/'breakout_profit_research'/'curves'/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes']
    assert len(trades)==len(entries)==sm['trades']
    assert abs(sm['net_pnl']-sum(x['net'] for x in trades))<1e-7
    assert abs(sum(x['funding'] for x in trades)-sum(x['actual_charge'] for x in funding))<1e-7
    eq=np.r_[1000.,curve.equity.to_numpy()];dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    assert abs(dd-sm['max_drawdown'])<1e-8
    for t in trades:
        raw=ticks.loc[t['observation_id']];side=1 if t['side']=='long' else -1
        assert t['entry_ts']==raw.entry_exec_ts and t['entry_ts']>=raw.decision_ts+5000
        assert np.isclose(t['raw_entry'],raw.raw_entry_5s,rtol=1e-11)
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        if '_hold_' in stem:assert side*(raw.raw_entry_5s-raw.level)>0
        assert t['exit_ts']<=t['quarter_end_ts']+M
        if t['reason']=='quarter_close_delay':
            assert t['exit_ts']==t['quarter_end_ts']+M
            key=(str(raw.source_year),raw.contract)
            if key not in opens:
                folder='breakout_november_2026' if key[0]=='2026' else f'breakout_{key[0]}_11'
                opens[key]=pd.read_parquet(ROOT/'work'/folder/'normalized'/f'{key[1]}_klines.parquet',columns=['ts','open']).set_index('ts').open
            assert np.isclose(t['raw_exit'],opens[key].loc[t['exit_ts']],rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(sm['slippage']+extra)),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert np.isclose(t['target'],t['entry']+side*sm['target_r']*t['initial_price_risk'],rtol=1e-11)
        trade_count+=1
out={'prior_feature_rows':count,'accounts_checked':len(summaries),'trade_records_checked':trade_count,
     'checks':'previous-quarter body/pace, previous 16 bars, ATR, known timestamps, entry/exit, costs, net ledger and drawdown'}
(HERE/'柱结束退出与账户独立对账.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('QUARTER_AUDIT_PASS',json.dumps(out,ensure_ascii=False),flush=True)
