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
RULES=json.loads((ROOT/'rules.json').read_text())

def load():
    universe=json.loads((ROOT/'universe.json').read_text())['selected']
    return {s:pd.read_feather(ROOT/'data'/f'{s}.feather').set_index('date').sort_index() for s in universe}

def features(data, index):
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
        out[symbol]=f.shift(1)
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

def simulate(data,start='2023-01-01',end='2026-10-31',fee=.001,mode='selection'):
    start=pd.Timestamp(start,tz='UTC');end=pd.Timestamp(end,tz='UTC')
    if start<pd.Timestamp(RULES['earliest_trade_date'],tz='UTC'):raise ValueError('Frozen universe cannot be used before 2023')
    index=pd.date_range(min(d.index.min() for d in data.values()),end,freq='D')
    f=features(data,index);bars={s:d.reindex(index) for s,d in data.items()}
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
        if weekly:
            pool=[s for s in pool if rank.get(s,999)<=10]
            for s in ordered[:6]:
                if len(pool)>=8:break
                if s not in pool and row[s]['volume']>=1e7:pool.append(s)
        btc=row.get('BTCUSDT',{})
        risk_on=bool(np.isfinite(btc.get('ma200',np.nan)) and btc['close']>btc['ma200'])
        valid=lambda s: (s in pool and row[s]['mom30']>0 and row[s]['close']>row[s]['ma100']
                         and np.isfinite(row[s]['vol']) and day>=cooldown.get(s,start))
        if mode=='baseline':
            pool=[s for s in ('BTCUSDT','ETHUSDT') if s in data]
            targets={s:.1 for s in pool if row[s]['mom30']>0 and day>=cooldown.get(s,start)}
            weekly=True
        elif mode=='selection':
            if weekly:
                chosen=sorted([s for s in pool if valid(s) and risk_on],
                              key=lambda s:(-row[s]['mom60']/max(row[s]['vol'],.005),s))[:4]
                targets=capped_weights(chosen,row)
            else:
                targets={s:p['weight'] for s,p in positions.items() if valid(s) and risk_on}
        else:raise ValueError(mode)
        trace.append({'date':str(day.date()),'information_through':str((day-pd.Timedelta(days=1)).date()),
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
            if op<=p['stop']:
                sell(s,p['qty'],op,day,'gap_stop');cooldown[s]=day+pd.Timedelta(days=2);continue
            if s not in targets:sell(s,p['qty'],op,day,'signal_or_pool_exit')
            elif weekly and mode=='selection':
                p['weight']=targets[s]
                desired=pre_equity*targets[s]/(op*(1+slip)*(1+fee))
                if desired<p['qty']*.9:sell(s,p['qty']-desired,op,day,'weekly_reduce')
        for s,w in targets.items():
            if day<cooldown.get(s,start):continue
            op=bars[s].at[day,'open']
            if not np.isfinite(op):continue
            existing=positions.get(s)
            if existing and (not weekly or mode=='baseline'):continue
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
                           'fee':qty*fill*fee,'pnl':None,'reason':'weekly_entry' if mode=='selection' else 'momentum'})
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
    return {'mode':mode,'start':str(start.date()),'end':str(end.date()),'fee':fee,'slippage':slip,
            'return_pct':(final/1000-1)*100,'max_drawdown':max(e['drawdown_pct'] for e in equity),
            'exit_fills':len(sells),'order_count':len(orders),'equity':equity,'orders':orders,'trace':trace,
            'missing_held_prices':issues,'valid_for_comparison':not issues,
            'mean_exposure':float(np.mean([e['exposure'] for e in equity]))}

def main():
    data=load();out=ROOT/'results';out.mkdir(exist_ok=True)
    paths=[ROOT/'rules.json',ROOT/'engine.py',ROOT/'universe.json']+sorted((ROOT/'data').glob('*.feather'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    frozen=ROOT/'frozen-code.json'
    if frozen.exists():
        if json.loads(frozen.read_text())['hashes']!=hashes:raise RuntimeError('Frozen study changed; create a new study version')
    else:frozen.write_text(json.dumps({'hashes':hashes,'created':pd.Timestamp.now(tz='UTC').isoformat(),
       'note':'Frozen before this study returns were calculated; history was previously observed, not independent unseen out-of-sample evidence.'},indent=2))
    summary=[]
    for start,end in [('2023-01-01','2024-12-31'),('2025-01-01','2026-10-31')]:
        for fee in [.001,.002,.003]:
            for mode in ['baseline','selection']:
                r=simulate(data,start,end,fee,mode)
                filename=f'{mode}-{start}-{end}-{fee}.json'
                (out/filename).write_text(json.dumps(r,ensure_ascii=False,allow_nan=False))
                row={k:v for k,v in r.items() if k not in ['equity','orders','trace','missing_held_prices']}
                row['missing_price_events']=len(r['missing_held_prices']);row['file']=filename
                summary.append(row);print(row,flush=True)
    (ROOT/'summary.json').write_text(json.dumps(summary,indent=2))

if __name__=='__main__':main()
