"""Point-in-time aggressor-flow hypotheses with a locked training selection."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
PARENT=HERE.parent/'大突破柱高杠杆研究_v1'
RELAXED=PARENT/'放宽入场研究'/'run_relaxed.py'
WORK=ROOT/'work'/'breakout_profit_research';WORK.mkdir(parents=True,exist_ok=True)
CURVES=WORK/'curves';CURVES.mkdir(exist_ok=True)
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','LTCUSDT','NEARUSDT']
M=60_000;Q=15*M
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
relaxed=load('flow_relaxed',RELAXED)
research=relaxed.research;forward=relaxed.f;eng=research.eng
forward.plan['fixed_pool']=[p for p in forward.plan['fixed_pool'] if p['symbol'] in SYMBOLS]
assert {p['symbol'] for p in forward.plan['fixed_pool']}==set(SYMBOLS)
relaxed.HERE=HERE;research.HERE=HERE
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,
        default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')
def enrich_flow(signals,norm):
    pieces=[];invalid=[]
    for contract in signals.contract.unique():
        raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','quote_volume','taker_buy_quote_volume']).set_index('ts')
        assert raw.index.is_unique
        group=signals[signals.contract==contract].copy();values=[]
        for r in group.itertuples(index=False):
            times=np.arange(int(r.quarter_start),int(r.decision_ts),M,dtype=np.int64)
            sub=raw.reindex(times)
            v=sub.quote_volume.to_numpy(float);b=sub.taker_buy_quote_volume.to_numpy(float)
            ok=len(times)>0 and np.isfinite(v).all() and np.isfinite(b).all() and (v>0).all() and (b>=0).all() and (b<=v*(1+1e-8)).all()
            val=int(r.side)*(2*float(b.sum())/float(v.sum())-1) if ok else np.nan
            if not ok:invalid.append(r.observation_id)
            values.append(val)
        group['directional_taker_imbalance']=values
        group['flow_known_ts']=group.decision_ts
        pieces.append(group)
    out=pd.concat(pieces,ignore_index=True).sort_values(['ts','symbol']).reset_index(drop=True)
    assert len(out)==len(signals) and out.observation_id.is_unique
    return out,invalid
def candidate(signals,name):
    if name.startswith('strong_'):return signals[signals.directional_taker_imbalance.ge(.10)].copy()
    if name.startswith('weak_'):return signals[signals.directional_taker_imbalance.lt(.10)].copy()
    return signals.copy()
def simulate(signals,name,start,end,market,guard,lev=20,scenario='main',period='',target_override=None,
             max_hold_minutes=60,allow_overnight=False,partial_exit=False,quarter_exit=False,failure_exit=False):
    fee,slip,delay,shock={'main':(.0005,.0005,0,0.),'stress':(.001,.001,0,.002),
                           'delay1':(.0005,.0005,1,0.)}[scenario]
    target=(1. if name.endswith('_1r') else 2.) if target_override is None else float(target_override)
    selected=candidate(signals,name)
    if len(selected) and name.startswith(('strong_','weak_')):assert selected.directional_taker_imbalance.notna().all()
    execution=selected.drop(columns=['large_1pct_label','large_halfpct_label','completed_body_pct'])
    sc={'id':scenario,'fee':fee,'slippage':slip,'delay_minutes':delay,'target_r':target,'leverage':lev,'stop_shock':shock,
        'max_hold_minutes':max_hold_minutes,'allow_overnight':allow_overnight,'partial_exit':partial_exit,'quarter_exit':quarter_exit,'failure_exit':failure_exit}
    sm,curve,trades,entries,funding=eng.simulate(sc,execution,start,end,market=market,guard=guard,save=False,run_id=name)
    labels=selected.set_index('observation_id')
    caught=[t for t in trades if t['entry_ts']<t['quarter_end_ts'] and bool(labels.at[t['observation_id'],'large_1pct_label'])]
    sm.update(period=period,run_id=name,position_leverage=lev,target_r=target,stop_shock=shock,
       max_hold_minutes=max_hold_minutes,allow_overnight=allow_overnight,partial_exit=partial_exit,quarter_exit=quarter_exit,failure_exit=failure_exit,
       net_win_rate_pct=sm['win_rate'] if trades else None,winning_trade_count=sum(t['net']>0 for t in trades),
       active_calendar_days=int(pd.DataFrame({'day':(curve.ts.to_numpy()-1)//86_400_000,'a':curve.active_in_minute}).groupby('day').a.any().sum()) if len(curve) else 0,
       large_1pct_caught=len(caught),large_1pct_trade_win=sum(t['net']>0 for t in caught),
       liquidation_proxy_count=sum(t['reason'].startswith('liquidation_proxy') for t in trades),
       planned_loss_exceeded_count=sum(-t['net']>t['planned_risk']+1e-9 for t in trades))
    sm['acceptance_pass']=bool(sm['valid_for_comparison'] and len(trades)>=100 and sm['active_calendar_days']>=30 and
        sm['net_win_rate_pct'] is not None and sm['net_win_rate_pct']>=60 and sm['net_pnl']>0 and
        sm['profit_factor'] is not None and sm['profit_factor']>1 and sm['max_drawdown']<=15)
    if sm['valid_for_comparison']:
        assert len(curve)==sm['expected_calendar_minutes'] and len(trades)==len(entries)
        assert abs(sm['final_equity']-1000-sum(t['net'] for t in trades))<1e-6
        assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in funding))<1e-6
    stem=f'{period}_{name}_{lev}x_{scenario}'
    dump(HERE/f'{stem}_summary.json',sm);dump(HERE/f'{stem}_trades.json',trades)
    dump(HERE/f'{stem}_entries.json',entries);dump(HERE/f'{stem}_funding.json',funding)
    curve.to_parquet(CURVES/f'{stem}.parquet',index=False)
    print('FLOW_RESULT',stem,json.dumps({k:sm.get(k) for k in ['signal_candidates','trades','net_win_rate_pct','net_pnl','profit_factor','max_drawdown','large_1pct_caught','liquidation_proxy_count','valid_for_comparison','issues']},default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),flush=True)
    return sm
def configure_2026():
    forward.NORM=ROOT/'work'/'breakout_november_2026'/'normalized'
    forward.WARM=int(pd.Timestamp('2026-04-01',tz='UTC').timestamp()*1000)
    forward.START=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
    forward.END=int(pd.Timestamp('2026-11-13',tz='UTC').timestamp()*1000)
    forward.GRID=np.arange(forward.WARM,forward.END,M,dtype=np.int64)
def run_development():
    configure_2026();market=forward.FixedMarket();guard=forward.FixedGuard(market)
    raw=relaxed.create_signals(market,guard);signals,invalid=enrich_flow(raw,forward.NORM)
    signals.to_parquet(HERE/'2026因果候选与事后标签.parquet',index=False)
    dump(HERE/'2026主动成交特征检查.json',{'candidates':len(signals),'invalid_flow_count':len(invalid),'invalid_ids':invalid,
        'flow_uses_minutes_strictly_before_decision':True,'pool':SYMBOLS})
    candidates=['base_1r','strong_1r','weak_1r','base_2r','strong_2r','weak_2r']
    train=[simulate(signals,n,'2026-05-01','2026-07-31',market,guard,20,'main','train_may_jul') for n in candidates]
    dump(HERE/'训练期全部候选.json',train)
    viable=[s for s in train if s['valid_for_comparison'] and s['trades']>=30]
    passed=[s for s in viable if s['net_win_rate_pct']>=60 and s['net_pnl']>0 and s['profit_factor'] is not None and s['profit_factor']>1]
    selected=max(passed or viable,key=lambda s:s['net_pnl']) if viable else None
    decision={'selected':selected['run_id'] if selected else None,'training_success':bool(passed),
      'selection_rule':'First choose among >=30 trades, >=60% net win, positive net and PF>1 if any; else largest net P&L among >=30 trades.',
      'selected_train_trades':selected['trades'] if selected else None,
      'selected_train_net_pnl':selected['net_pnl'] if selected else None,
      'plan_sha256':hashlib.sha256((HERE/'研究计划与筛选标准.json').read_bytes()).hexdigest(),
      'training_results_sha256':hashlib.sha256((HERE/'训练期全部候选.json').read_bytes()).hexdigest(),
      'note':'Selection is based on exploratory May–July 2026 only; do not revise after reading later periods.'}
    dump(HERE/'冻结选定候选.json',decision)
    print('LOCKED_SELECTION',json.dumps(decision,ensure_ascii=False),flush=True)
    if not selected:return
    periods=[('later_aug_oct','2026-08-01','2026-10-31'),('full_2026','2026-05-01','2026-10-31'),
             ('nov12_2026','2026-11-01','2026-11-12')]
    results=[]
    for label,start,end in periods:
      for lev in (10,20):
       for scenario in ('main','stress','delay1'):
        results.append(simulate(signals,selected['run_id'],start,end,market,guard,lev,scenario,label))
    dump(HERE/'2026冻结候选各情景.json',results)
    pd.DataFrame(results).to_csv(HERE/'2026冻结候选各情景.csv',index=False,encoding='utf-8-sig')
    print('FLOW_DEVELOPMENT_COMPLETE',len(results),flush=True)
if __name__=='__main__':run_development()
