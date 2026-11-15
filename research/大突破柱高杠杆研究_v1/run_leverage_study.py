"""Frozen, isolated retrospective research; no orders and no model deployment."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
PREV=HERE.parent/'突破胜率与净收益前瞻检验_v1'
RECENT=HERE.parent/'突破失败与利润保护研究_v1'
WORK=ROOT/'work'/'breakout_november_2026'
CURVES=WORK/'leverage_curves';CURVES.mkdir(exist_ok=True,parents=True)
M=60_000;Q=15*M
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
forward=load('bigbar_forward',PREV/'forward_research.py')
eng=load('bigbar_engine',HERE/'leveraged_engine.py')
forward.NORM=WORK/'normalized'
forward.START=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
forward.END=int(pd.Timestamp('2026-11-13',tz='UTC').timestamp()*1000)
forward.GRID=np.arange(forward.WARM,forward.END,M,dtype=np.int64)
PERIODS=[('fixed_full','2026-05-01','2026-10-31'),('may_jul','2026-05-01','2026-07-31'),
         ('aug_oct','2026-08-01','2026-10-31'),('nov_12days','2026-11-01','2026-11-12')]
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,
        default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')
def bounds(start,end):
    return int(pd.Timestamp(start,tz='UTC').timestamp()*1000),int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)

def make_features(market,guard):
    first=pd.concat([pd.read_parquet(PREV/'first_signals.parquet'),pd.read_parquet(RECENT/'first_signals.parquet')],ignore_index=True)
    assert len(first)==106 and first.observation_id.is_unique
    enriched=[];universe={k:{'valid_15m_bars':0,'large_1pct':0,'large_halfpct':0} for k,_,_ in PERIODS}
    for symbol,contract in guard.mapping.items():
        a=market.trade[contract];valid=forward.valid_trade(a);f=forward.prior.calculate(a,valid)
        quarters=a.reshape(-1,15,7);qvalid=valid.reshape(-1,15).all(axis=1)
        qopen=quarters[:,0,0];qclose=quarters[:,-1,3]
        up=f['upper'].reshape(-1,15)[:,0];down=f['lower'].reshape(-1,15)[:,0]
        with np.errstate(divide='ignore',invalid='ignore'):
            signed=(qclose-qopen)/qopen
        large1=qvalid & (((signed>=.01)&(qclose>up))|((signed<=-.01)&(qclose<down)))
        largehalf=qvalid & (((signed>=.005)&(qclose>up))|((signed<=-.005)&(qclose<down)))
        quarter_ts=forward.GRID[::15]
        for name,start,end in PERIODS:
            lo,hi=bounds(start,end);mask=(quarter_ts>=lo)&(quarter_ts<hi)
            universe[name]['valid_15m_bars']+=int((qvalid&mask).sum())
            universe[name]['large_1pct']+=int((large1&mask).sum())
            universe[name]['large_halfpct']+=int((largehalf&mask).sum())
        for _,r in first[first.contract==contract].iterrows():
            rec=r.to_dict();i=int((int(r.break_ts)-forward.WARM)//M);q=i//15*15;side=int(r.side)
            assert forward.GRID[i]==r.break_ts and valid[q:i+1].all()
            assert np.isclose(a[i,3],r.signal_close,rtol=1e-11)
            ratio=float(f['ratio'][i]);body=side*(float(a[i,3])-float(a[q,0]))/float(r.atr)
            stop=float(a[q:i+1,2].min()-.1*r.atr if side==1 else a[q:i+1,1].max()+.1*r.atr)
            end=q+14;assert valid[q:end+1].all()
            close=float(a[end,3]);body_pct=side*(close-float(a[q,0]))/float(a[q,0])
            beyond=side*(close-float(r.level))>0
            rec.update(own_trade_count_ratio=ratio,partial_body_atr=body,structure_stop=stop,
                       large_1pct_label=bool(body_pct>=.01 and beyond),
                       large_halfpct_label=bool(body_pct>=.005 and beyond),
                       completed_body_pct=100*body_pct,
                       strength_pass=bool(np.isfinite(ratio) and ratio>=1.5 and body>=.25))
            enriched.append(rec)
        print('FEATURES',symbol,'candidate_count',len(enriched),flush=True)
    features=pd.DataFrame(enriched).sort_values(['ts','symbol']).reset_index(drop=True)
    assert len(features)==len(first)
    features.to_parquet(HERE/'候选信号及事后大柱标签.parquet',index=False)
    features.to_csv(HERE/'候选信号及事后大柱标签.csv',index=False,encoding='utf-8-sig')
    dump(HERE/'全池大突破柱总数.json',universe)
    return features,universe

def run_one(period,start,end,variant,signals,market,guard,lev,scenario,universe):
    name,fee,slip,delay,shock=scenario
    target=3. if variant.endswith('_3r') else 2.
    sc={'id':name,'fee':fee,'slippage':slip,'delay_minutes':delay,'target_r':target,
        'leverage':lev,'stop_shock':shock}
    # Completed-candle outcomes are labels only and never enter the trading engine.
    execution_signals=signals.drop(columns=['large_1pct_label','large_halfpct_label','completed_body_pct'])
    sm,curve,trades,entries,funding=eng.simulate(sc,execution_signals,start,end,market=market,guard=guard,save=False,run_id=variant)
    sm.update(period=period,run_id=variant,position_leverage=lev,stop_shock=shock,
              winning_trade_count=sum(t['net']>0 for t in trades),
              net_win_rate_pct=sm['win_rate'] if trades else None,
              liquidation_proxy_count=sum(t['reason'].startswith('liquidation_proxy') for t in trades),
              planned_loss_exceeded_count=sum(-t['net']>t['planned_risk']+1e-9 for t in trades),
              active_calendar_days=int(pd.DataFrame({'day':(curve.ts.to_numpy()-1)//86_400_000,'a':curve.active_in_minute}).groupby('day').a.any().sum()) if len(curve) else 0)
    labels=signals.set_index('observation_id')
    in_quarter=[t for t in trades if t['entry_ts']<t['quarter_end_ts']]
    big=[t for t in in_quarter if bool(labels.at[t['observation_id'],'large_1pct_label'])]
    half=[t for t in in_quarter if bool(labels.at[t['observation_id'],'large_halfpct_label'])]
    sm.update(in_original_quarter=len(in_quarter),large_1pct_caught=len(big),
              large_1pct_trade_win=sum(t['net']>0 for t in big),large_halfpct_caught=len(half),
              large_1pct_universe=universe[period]['large_1pct'],
              average_entry_notional=float(np.mean([t['entry_notional'] for t in trades])) if trades else None,
              average_isolated_margin=float(np.mean([t['isolated_margin'] for t in trades])) if trades else None)
    sm['acceptance_pass']=bool(sm['valid_for_comparison'] and len(trades)>=100 and sm['active_calendar_days']>=30 and
        sm['net_win_rate_pct'] is not None and sm['net_win_rate_pct']>=60 and sm['net_pnl']>0 and
        sm['profit_factor'] is not None and sm['profit_factor']>1 and sm['max_drawdown']<=15)
    if sm['valid_for_comparison']:
        assert len(curve)==sm['expected_calendar_minutes'] and len(trades)==len(entries)
        assert abs(sm['final_equity']-1000-sum(t['net'] for t in trades))<1e-6
        assert abs(sum(t['funding'] for t in trades)-sum(f['actual_charge'] for f in funding))<1e-6
        for t,e in zip(trades,entries):
            assert abs(t['isolated_margin']-t['entry_notional']/lev)<1e-7
            assert e['planned_loss']<=e['known_equity']*.0025+1e-7
    stem=f'{period}_{variant}_{lev}x_{name}'
    dump(HERE/f'{stem}_summary.json',sm);dump(HERE/f'{stem}_trades.json',trades)
    dump(HERE/f'{stem}_entries.json',entries);dump(HERE/f'{stem}_funding.json',funding)
    curve.to_parquet(CURVES/f'{stem}.parquet',index=False)
    print('LEVERAGE_RESULT',stem,json.dumps({k:sm.get(k) for k in ['trades','net_win_rate_pct','net_pnl','max_drawdown','large_1pct_caught','large_1pct_trade_win','liquidation_proxy_count','planned_loss_exceeded_count','valid_for_comparison','issues']},default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),flush=True)
    return sm

def main():
    market=forward.FixedMarket();guard=forward.FixedGuard(market)
    features,universe=make_features(market,guard)
    stronger=features[features.strength_pass].copy()
    structure=stronger.copy();structure['stop_price']=structure['structure_stop']
    variants=[('base_2r',features),('strength_2r',stronger),('strength_3r',stronger),('structure_3r',structure)]
    scenarios=[('main',.0005,.0005,0,0.),('stress',.001,.001,0,.002),('delay1',.0005,.0005,1,0.)]
    results=[]
    for period,start,end in PERIODS:
      for variant,signals in variants:
       for lev in (5,10,20):
        for scenario in scenarios:
            results.append(run_one(period,start,end,variant,signals,market,guard,lev,scenario,universe))
    dump(HERE/'全部账户结果.json',results)
    cols=['period','run_id','position_leverage','scenario','signal_candidates','trades','winning_trade_count','net_win_rate_pct',
          'net_pnl','return_pct','max_drawdown','intrabar_stress_dd','profit_factor','active_calendar_days',
          'in_original_quarter','large_1pct_caught','large_1pct_trade_win','large_halfpct_caught','large_1pct_universe',
          'average_entry_notional','average_isolated_margin','liquidation_proxy_count','planned_loss_exceeded_count',
          'valid_for_comparison','acceptance_pass','issues']
    pd.DataFrame(results).reindex(columns=cols).to_csv(HERE/'大突破高杠杆完整对照.csv',index=False,encoding='utf-8-sig')
    print('LEVERAGE_STUDY_COMPLETE',len(results),flush=True)

if __name__=='__main__':main()
