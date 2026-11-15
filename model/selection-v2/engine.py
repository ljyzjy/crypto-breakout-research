"""Causal daily portfolio research. Decisions for day t only read rows before t.

Signals and simulated execution are separate. Today's OHLC can determine a fill,
never today's decision. Missing held-asset prices are reported, never 'liquidated'
at a conveniently chosen last price. No automatic paper/live deployment.
"""
import hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'selection-v1'
RULES=json.loads((SOURCE/'rules.json').read_text())

def load():
    universe=json.loads((SOURCE/'universe.json').read_text())['selected']
    return {s:pd.read_feather(SOURCE/'data'/f'{s}.feather').set_index('date').sort_index() for s in universe}

def features(data, index, extra_lag=0):
    out={}
    for symbol,raw in data.items():
        d=raw.reindex(index)
        c=d.close
        f=pd.DataFrame(index=index)
        f['close']=c
        f['volume']=d.quote_volume.rolling(30,min_periods=28).median()
        f['count']=c.rolling(30,min_periods=1).count()
        f['age']=(index-raw.index.min()).days
        f['mom30']=c/c.shift(30)-1
        f['mom60']=c/c.shift(60)-1
        f['ma100']=c.rolling(100,min_periods=100).mean()
        f['ma200']=c.rolling(200,min_periods=200).mean()
        f['vol']=c.pct_change(fill_method=None).rolling(60,min_periods=50).std()
        # Every input, including eligibility and history age, becomes available next UTC day.
        out[symbol]=f.shift(1+extra_lag)
    return out

def capped_weights(names,f,budget=.2,cap=.08):
    pending=set(names);weights={s:0.0 for s in names};left=budget
    while pending and left>1e-12:
        scores={s:1/max(float(f[s]['vol']),.005) for s in pending}
        total=sum(scores.values());proposal={s:left*scores[s]/total for s in pending}
        capped=[s for s,w in proposal.items() if w>cap]
        if not capped:
            weights.update(proposal);break
        for s in capped:weights[s]=cap;left-=cap;pending.remove(s)
    return weights

def simulate(data,start='2023-01-01',end='2026-10-31',fee=.001,mode='selection',extra_lag=0):
    start=pd.Timestamp(start,tz='UTC');end=pd.Timestamp(end,tz='UTC')
    if start<pd.Timestamp(RULES['earliest_trade_date'],tz='UTC'):raise ValueError('Frozen universe cannot be used before 2023')
    index=pd.date_range(min(d.index.min() for d in data.values()),end,freq='D')
    f=features(data,index,extra_lag);bars={s:d.reindex(index) for s,d in data.items()}
    v1_modes={'selection','no_market_gate','no_ma100','daily_vacancy_entry','equal_weights','no_rebalance'}
    resize=mode in v1_modes and mode!='no_rebalance'
    pool=[];positions={};cooldown={};cash=1000.;last={};trace=[];equity=[];orders=[];issues=[]
    slip=RULES['slippage'];pre_equity=1000.;peak=1000.
    def sell(symbol,amount,price,day,reason):
        nonlocal cash
        p=positions[symbol];amount=min(amount,p['qty']);fill=price*(1-slip)
        proceeds=amount*fill*(1-fee);cost=p['cost']*amount/p['qty'];cash+=proceeds
        orders.append({'date':str(day.date()),'symbol':symbol,'side':'sell','qty':amount,'price':fill,
                       'fee':amount*fill*fee,'pnl':proceeds-cost,'reason':reason})
        p['qty']-=amount;p['cost']-=cost
        if p['qty']<1e-12:del positions[symbol]
    for day in index[index>=start]:
        row={s:frame.loc[day].to_dict() for s,frame in f.items()}
        hard=lambda s: (np.isfinite(row[s]['close']) and row[s]['age']>=180 and row[s]['count']>=28
                        and np.isfinite(row[s]['volume']) and row[s]['volume']>=5e6)
        ordered=sorted([s for s in data if hard(s)],key=lambda s:(-row[s]['volume'],s))
        rank={s:i+1 for i,s in enumerate(ordered)}
        weekly=(day.day_of_week==0 or day==start)
        old_pool=pool.copy();pool=[s for s in pool if hard(s)]
        limit,retain,entry=(4,6,4) if mode=='liquidity4' else (8,10,6)
        if weekly:
            pool=[s for s in pool if rank.get(s,999)<=retain]
            for s in ordered[:entry]:
                if len(pool)>=limit:break
                if s not in pool and row[s]['volume']>=1e7:pool.append(s)
        btc=row.get('BTCUSDT',{})
        risk_on=bool(np.isfinite(btc.get('ma200',np.nan)) and btc['close']>btc['ma200'])
        valid=lambda s: (s in pool and row[s]['mom30']>0 and (mode=='no_ma100' or row[s]['close']>row[s]['ma100'])
                         and np.isfinite(row[s]['vol']) and day>=cooldown.get(s,start))
        if mode=='baseline':
            pool=[s for s in ('BTCUSDT','ETHUSDT') if s in data]
            targets={s:.1 for s in pool if row[s]['mom30']>0 and day>=cooldown.get(s,start)}
            weekly=True
        elif mode in v1_modes:
            if weekly:
                chosen=sorted([s for s in pool if valid(s) and (risk_on or mode=='no_market_gate')],
                              key=lambda s:(-row[s]['mom60']/max(row[s]['vol'],.005),s))[:4]
                targets=({s:min(.08,.2/len(chosen)) for s in chosen} if mode=='equal_weights' and chosen else capped_weights(chosen,row))
            else:
                targets={s:p['weight'] for s,p in positions.items() if valid(s) and (risk_on or mode=='no_market_gate')}
                if mode=='daily_vacancy_entry' and risk_on:
                    spare=max(0,.2-sum(targets.values()))
                    chosen=sorted([s for s in pool if s not in targets and valid(s)],key=lambda s:(-row[s]['mom60']/max(row[s]['vol'],.005),s))[:max(0,4-len(targets))]
                    targets.update(capped_weights(chosen,row,budget=spare))
        elif mode=='liquidity4':
            targets={s:.05 for s in pool if row[s]['mom30']>0 and day>=cooldown.get(s,start)}
        elif mode in ('relative4','core_satellite'):
            core=('BTCUSDT','ETHUSDT') if mode=='core_satellite' else ()
            eligible=sorted([s for s in pool if s not in core and row[s]['mom30']>0 and day>=cooldown.get(s,start)],key=lambda s:(-row[s]['mom30'],s))
            keep_rank=2 if core else 6; slots=1 if core else 4
            if weekly:
                chosen=[s for s in eligible[:keep_rank] if s in positions][:slots]
                for s in eligible[:slots]:
                    if len(chosen)>=slots:break
                    if s not in chosen:chosen.append(s)
            else:chosen=[s for s in positions if s in eligible]
            targets={s:.05 for s in chosen}
            if core:
                targets.update({s:.075 for s in core if hard(s) and row[s]['mom30']>0 and day>=cooldown.get(s,start)})
        else:raise ValueError(mode)
        trace.append({'date':str(day.date()),'information_through':str((day-pd.Timedelta(days=1+extra_lag)).date()),
                      'pool':pool.copy(),'entered':[s for s in pool if s not in old_pool],
                      'removed':[s for s in old_pool if s not in pool],'risk_on':risk_on,
                      'weights':targets.copy(),'ranks':rank,'features':{
                          s:{k:None if not np.isfinite(v) else float(v) for k,v in row[s].items()}
                          for s in data}})
        # Orders are decided above; today's open is used solely to simulate their execution.
        for s in list(positions):
            op=bars[s].at[day,'open']
            if not np.isfinite(op):
                issues.append({'date':str(day.date()),'symbol':s,'reason':'held_asset_missing_price'});continue
            p=positions[s]
            if weekly and mode in v1_modes and s in targets:p['weight']=targets[s]
            if op<=p['stop']:
                sell(s,p['qty'],op,day,'gap_stop');cooldown[s]=day+pd.Timedelta(days=2);continue
            if s not in targets:sell(s,p['qty'],op,day,'signal_or_pool_exit')
            elif weekly and resize:
                p['weight']=targets[s]
                desired=pre_equity*targets[s]/(op*(1+slip)*(1+fee))
                if desired<p['qty']*.9:sell(s,p['qty']-desired,op,day,'weekly_reduce')
        for s,w in targets.items():
            if day<cooldown.get(s,start):continue
            op=bars[s].at[day,'open']
            if not np.isfinite(op):continue
            existing=positions.get(s)
            if existing and (not weekly or not resize):continue
            fill=op*(1+slip);budget=pre_equity*w
            current=existing['qty']*fill*(1+fee) if existing else 0
            spend=min(cash,max(0,budget-current))
            if spend<10 or (existing and spend<budget*.1):continue
            qty=spend/(fill*(1+fee));cash-=spend
            if existing:
                existing['qty']+=qty;existing['cost']+=spend;existing['weight']=w
                # Never loosen an existing protective stop when adding.
                existing['stop']=max(existing['stop'],fill*.96)
            else:positions[s]={'qty':qty,'cost':spend,'stop':fill*.96,'weight':w}
            orders.append({'date':str(day.date()),'symbol':s,'side':'buy','qty':qty,'price':fill,
                           'fee':qty*fill*fee,'pnl':None,'reason':('weekly_entry' if mode in v1_modes else 'momentum' if mode=='baseline' else 'signal_entry')})
        for s in list(positions):
            low=bars[s].at[day,'low']
            if np.isfinite(low) and low<=positions[s]['stop']:
                sell(s,positions[s]['qty'],positions[s]['stop'],day,'intraday_stop')
                cooldown[s]=day+pd.Timedelta(days=2)
        for s in data:
            close=bars[s].at[day,'close']
            if np.isfinite(close):last[s]=close
        marked=cash+sum(p['qty']*last.get(s,0) for s,p in positions.items())
        peak=max(peak,marked);pre_equity=marked
        equity.append({'date':str(day.date()),'equity':marked,'drawdown_pct':(1-marked/peak)*100,
                       'cash':cash,'exposure':(marked-cash)/marked,'holdings':list(positions)})
    # Administrative end-of-window close: not a strategy signal, and never uses a stale price.
    for s in list(positions):
        px=bars[s].at[end,'close']
        if np.isfinite(px):sell(s,positions[s]['qty'],px,end,'window_end')
    final=cash+sum(p['qty']*last.get(s,0) for s,p in positions.items())
    equity[-1].update(equity=final,cash=cash,drawdown_pct=(1-final/peak)*100)
    sells=[o for o in orders if o['side']=='sell']
    return {'mode':mode,'extra_lag':extra_lag,'start':str(start.date()),'end':str(end.date()),'fee':fee,'slippage':slip,
            'return_pct':(final/1000-1)*100,'max_drawdown':max(e['drawdown_pct'] for e in equity),
            'exit_fills':len(sells),'order_count':len(orders),'equity':equity,'orders':orders,'trace':trace,
            'missing_held_prices':issues,'valid_for_comparison':not issues,
            'mean_exposure':float(np.mean([e['exposure'] for e in equity]))}
