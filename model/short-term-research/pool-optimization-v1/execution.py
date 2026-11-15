"""Frozen original execution flow with logged stop/retry substitutions only."""
import math
import numpy as np
import pandas as pd
from st_engine import MODES,NAMES,HOLD,inputs,features,compress_curve
SYMBOLS=()
POLICIES={}
def simulate_path(start,end,policy,fee=.001,resolution='1h',delay=0,data=None,signal_frames=None,full_curve=False,stop_frames=None):
    if policy not in POLICIES:raise ValueError('Unregistered sizing policy')
    mode='DailyMomentum'
    if mode not in MODES or resolution not in ('1h','5m') or delay not in (0,5):raise ValueError('Unsupported fixed scenario')
    if delay and resolution!='5m':raise ValueError('Delay requires five-minute bars')
    if data is None:data,signal_frames=inputs()
    if signal_frames is None:signal_frames={s:features(data[(s,'1h')]) for s in SYMBOLS}
    budgets=sizing_frames(data,policy)
    begin=pd.Timestamp(start,tz='UTC');finish=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)
    step=3600 if resolution=='1h' else 300
    index=pd.date_range(begin,finish-pd.Timedelta(seconds=step),freq=f'{step}s')
    times=index.as_unit('s').asi8;frame={s:data[(s,resolution)].reindex(index) for s in SYMBOLS}
    prices={s:frame[s][['open','low','close','volume']].to_numpy() for s in SYMBOLS}
    # decision_t is strictly after the source hour's close; never merge future hours backward.
    decision_times=index-pd.Timedelta(minutes=delay)
    decision=(decision_times.minute==0)&(decision_times.second==0)
    src=decision_times-pd.Timedelta(hours=1)
    sizes={s:budgets[s].reindex(src).fillna(0).to_numpy(dtype=float) for s in SYMBOLS}
    distances={s:stop_frames[s].reindex(src).fillna(.04).to_numpy(dtype=float) for s in SYMBOLS}
    signals={s:signal_frames[s].reindex(src)[[mode+'_buy',mode+'_sell']].fillna(False).to_numpy(dtype=bool) for s in SYMBOLS}
    cash=1000.;positions={};last={};cooldown={};guard_until=0;stops=[];trades=[];orders=[];curve=[];gaps=[]
    peak=1000.;maxdd=0.;exposure_sum=0.;cash_min=1000.;guards=0;blocked=0;slip=.0005
    curve.append([int(times[0]),1000.,0.,0.])

    def close(s,ref,ts,reason,information_time):
        nonlocal cash,guard_until,guards
        p=positions.pop(s);fill=ref*(1-slip);exitfee=p['qty']*fill*fee
        proceeds=p['qty']*fill-exitfee;cash+=proceeds;pnl=proceeds-p['cost']
        slip_cost=p['qty']*(p['fill']-p['ref']+ref-fill)
        fees=p['entry_fee']+exitfee
        t={'symbol':s,'entry_ts':p['ts'],'exit_ts':int(ts),'entry_price':p['fill'],'exit_price':fill,
           'entry_reference':p['ref'],'exit_reference':ref,'qty':p['qty'],'stake':p['stake'],'pnl':pnl,
           'stop_distance':p['stop_distance'],'planned_stop_loss':p['stake']*p['stop_distance'],'return_pct':pnl/p['cost']*100,'fees':fees,'slippage':slip_cost,'gross_pnl':pnl+fees+slip_cost,
           'hold_hours':(ts-p['ts'])/3600,'reason':reason}
        trades.append(t);orders.append({'side':'sell','symbol':s,'ts':int(ts),'information_ts':information_time,'price':fill,'qty':p['qty'],'cash':cash,'reason':reason})
        cooldown[s]=math.ceil((ts+6*3600)/3600)*3600
        if POLICIES[policy]['retry'] and reason in ('gap_stop','stop_loss') and pnl<0:
            midnight=pd.Timestamp(ts,unit='s',tz='UTC').normalize()
            next_week=int((midnight+pd.Timedelta(days=7-midnight.weekday())).timestamp())
            cooldown[s]=max(cooldown[s],next_week)
        if reason in ('gap_stop','stop_loss') and pnl<0:
            stops.append(ts)
            if sum(t0>=ts-48*3600 for t0 in stops)>=2:
                guard_until=max(guard_until,math.ceil((ts+24*3600)/3600)*3600);guards+=1

    for i,ts in enumerate(times):
        ts=int(ts);endts=ts+step;is_decision=bool(decision[i]);info=int(ts-delay*60) if is_decision else None
        for s in list(positions):
            op,low,cp,vol=prices[s][i]
            if not np.isfinite(op):
                gaps.append({'ts':ts,'symbol':s,'kind':'held_missing_price'});continue
            if vol>0 and op<=positions[s]['stop']:close(s,op,ts,'gap_stop',info)
        if is_decision:
            for s in list(positions):
                op,low,cp,vol=prices[s][i];p=positions[s]
                if not (np.isfinite(op) and vol>0):continue
                due=HOLD[mode] is not None and info-p['ts']>=HOLD[mode]*3600
                if signals[s][i,1] or due:close(s,op,ts,'signal_exit' if signals[s][i,1] else 'time_exit',info)
            for s in SYMBOLS:
                op,low,cp,vol=prices[s][i];buy,sell=signals[s][i]
                if s in positions or not buy or sell or not (np.isfinite(op) and vol>0):continue
                if ts<cooldown.get(s,0) or ts<guard_until:blocked+=1;continue
                stake=float(sizes[s][i])
                if policy=='inverse_vol_pair':stake=min(stake,max(0.,200-sum(p['stake'] for p in positions.values())))
                if stake<10 or len(positions)>=2 or cash<stake*(1+fee):continue
                fill=float(op)*(1+slip);qty=stake/fill;entryfee=stake*fee;cost=stake+entryfee;cash-=cost
                positions[s]={'ref':float(op),'fill':fill,'qty':qty,'cost':cost,'entry_fee':entryfee,'stop':fill*(1-float(distances[s][i])),'ts':ts,'stake':stake,'stop_distance':float(distances[s][i])}
                orders.append({'side':'buy','symbol':s,'ts':ts,'information_ts':info,'price':fill,'qty':qty,'cash':cash,'reason':'entry'})
        # Only now is the execution bar's low observed. No symbol can use that future low to block an earlier entry.
        for s in list(positions):
            op,low,cp,vol=prices[s][i]
            if np.isfinite(low) and vol>0 and low<=positions[s]['stop']:close(s,positions[s]['stop'],endts,'stop_loss',None)
        for s in SYMBOLS:
            cp=prices[s][i,2]
            if np.isfinite(cp):last[s]=float(cp)
        value=sum(p['qty']*last[s] for s,p in positions.items());equity=cash+value
        peak=max(peak,equity);dd=(1-equity/peak)*100;maxdd=max(maxdd,dd);exposure=value/equity
        exposure_sum+=exposure;cash_min=min(cash_min,cash)
        if full_curve or step==3600 or endts%3600==0:curve.append([endts,equity,dd,exposure])
    for s in list(positions):
        cp=prices[s][-1,2];vol=prices[s][-1,3]
        if np.isfinite(cp) and vol>0:close(s,float(cp),int(times[-1]+step),'window_end',None)
        else:gaps.append({'ts':int(times[-1]),'symbol':s,'kind':'cannot_close_at_window_end'})
    final=cash+sum(p['qty']*last[s] for s,p in positions.items());maxdd=max(maxdd,(1-final/peak)*100)
    curve[-1]=[int(times[-1]+step),final,(1-final/peak)*100,0. if not positions else curve[-1][3]]
    pnls=[t['pnl'] for t in trades];wins=[x for x in pnls if x>0];losses=[x for x in pnls if x<0]
    reconcile=abs(1000+sum(pnls)-final) if not positions else None
    if cash_min < -1e-7 or (reconcile is not None and reconcile>1e-7):raise AssertionError('Ledger/cash constraint failed')
    return {'mode':policy,'name':POLICIES[policy]['name'],'start':start,'end':end,'fee':fee,'slippage':slip,'resolution':resolution,'delay_minutes':delay,
            'initial':1000,'final_equity':final,'return_pct':(final/1000-1)*100,'max_drawdown':maxdd,'trade_count':len(trades),
            'win_rate':len(wins)/len(trades)*100 if trades else 0.,'profit_factor':sum(wins)/-sum(losses) if losses else None,
            'mean_trade_pnl':float(np.mean(pnls)) if pnls else 0.,'median_trade_pnl':float(np.median(pnls)) if pnls else 0.,
            'mean_hold_hours':float(np.mean([t['hold_hours'] for t in trades])) if trades else 0.,
            'mean_exposure_pct':exposure_sum/len(times)*100,'fees':sum(t['fees'] for t in trades),'slippage_cost':sum(t['slippage'] for t in trades),
            'gross_pnl':sum(t['gross_pnl'] for t in trades),'turnover':sum(t['qty']*(t['entry_price']+t['exit_price']) for t in trades)/1000,
            'top3_profit_share':sum(sorted(wins,reverse=True)[:3])/sum(wins)*100 if wins else None,
            'contributions':{s:sum(t['pnl'] for t in trades if t['symbol']==s) for s in SYMBOLS},
            'guard_activations':guards,'blocked_entry_signals':blocked,'data_issues':gaps,'valid_for_comparison':not gaps,
            'cash_min':cash_min,'ledger_error':reconcile,'open_positions':len(positions),
            'trades':trades,'orders':orders,'curve':curve if full_curve else compress_curve(curve),
            'max_drawdown_basis':'all execution-bar closing valuations; chart sampled to hours then compressed; not intrabar worst loss'}
