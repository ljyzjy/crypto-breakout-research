"""Perpetual economic replay with verified non-binding collateral constraints."""
from pathlib import Path
from functools import lru_cache
import sys,math,hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent
RESEARCH=ROOT.parent
sys.path.insert(0,str(RESEARCH));sys.path.insert(0,str(RESEARCH/'public-research-v1'))
import st_engine as engine
import public_engine as public
MODES=('DailyMomentum',*public.VARIANTS)
NAMES={**engine.NAMES,**{k:v['name'] for k,v in public.VARIANTS.items()}}

@lru_cache(maxsize=1)
def inputs():
 manifest=engine.read(ROOT/'data-manifest.json');data=dict(engine.inputs()[0]);marks={};funding={}
 for item in manifest['summary']:
  path=ROOT/item['processed'];assert hashlib.sha256(path.read_bytes()).hexdigest()==item['processed_sha256']
  d=pd.read_parquet(path);s=item['symbol'];kind=item['kind']
  if kind=='fundingRate':
   exact=pd.to_datetime(d.calc_time,unit='ms',utc=True);scheduled=exact.dt.round('h')
   assert (exact-scheduled).dt.total_seconds().abs().max()<60
   funding[s]=pd.Series(d.last_funding_rate.to_numpy(),index=scheduled)
  else:
   d.index=pd.to_datetime(d.open_time,unit='ms',utc=True)
   if kind=='klines':data[(s,'5m')]=d[['open','high','low','close','volume']]
   else:marks[s]=d[['open','high','low','close']]
 return data,marks,funding

@lru_cache(maxsize=40)
def base_run(start,end,mode,fee,delay):
 data,_,_=inputs()
 fs=engine.inputs()[1] if mode=='DailyMomentum' else public.cached_signals(mode)
 r=engine.simulate(start,end,'DailyMomentum',fee,'5m',delay,data=data,signal_frames=fs)
 assert r['valid_for_comparison'] and not r['open_positions']
 return r

def replay(base,marks,funding,leverage):
 assert leverage in (1,2,3)
 start=base['start'];end=base['end'];fee=base['fee'];slip=base['slippage']
 index=pd.date_range(pd.Timestamp(start,tz='UTC'),pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1),freq='5min',inclusive='left')
 seconds=index.as_unit('s').asi8
 m={s:marks[s].reindex(index).to_numpy() for s in engine.SYMBOLS}
 assert all(np.isfinite(a).all() for a in m.values())
 f={s:funding[s].reindex(index).fillna(0).to_numpy() for s in engine.SYMBOLS}
 open_events={};stop_events={};final=[]
 for o in base['orders']:
  if o['reason']=='window_end':final.append(o)
  elif o['reason']=='stop_loss':stop_events.setdefault(o['ts'],[]).append(o)
  else:open_events.setdefault(o['ts'],[]).append(o)
 pos={};cash=1000.;peak=1000.;maxdd=0.;mincash=1000.;minimum_ratio=1e9;maxgross=0.;totalexp=0.
 trades=[];orders=[];funding_events=[];issues=[];curve=[[int(seconds[0]),1000.,0.,0.]]

 def settle(s,rate,mark,ts,boundary_new=False):
  if boundary_new and rate<=0:return
  amount=pos[s]['qty']*mark*rate;pos[s]['funding']+=amount
  if amount:funding_events.append({'symbol':s,'ts':int(ts),'rate':float(rate),'mark':float(mark),'payment':float(amount),'new_boundary_entry':boundary_new})

 def close(o):
  nonlocal cash
  s=o['symbol'];p=pos.pop(s);qty=p['qty'];exitfee=qty*o['price']*fee
  pricepnl=qty*(o['price']-p['price']);net=pricepnl-p['entryfee']-exitfee-p['funding']
  cash+=100+pricepnl-exitfee-p['funding']
  refexit=o['price']/(1-slip);refentry=p['price']/(1+slip)
  slippage=qty*(p['price']-refentry+refexit-o['price'])
  trades.append({'symbol':s,'entry_ts':p['ts'],'exit_ts':o['ts'],'entry_price':p['price'],'exit_price':o['price'],'qty':qty,'margin':100.,'notional':100.*leverage,'pnl':net,'price_pnl_after_slippage':pricepnl,'fees':p['entryfee']+exitfee,'slippage':slippage,'funding':p['funding'],'hold_hours':(o['ts']-p['ts'])/3600,'reason':o['reason']})
  orders.append({**o,'qty':qty,'cash':cash})

 for i,ts in enumerate(seconds):
  ts=int(ts)
  for s in list(pos):settle(s,f[s][i],m[s][i,0],ts)
  for o in open_events.get(ts,[]):
   s=o['symbol']
   if o['side']=='sell':close(o)
   else:
    cost=100+100*leverage*fee
    if cash<cost:issues.append({'ts':ts,'kind':'insufficient_free_cash','cash':cash})
    cash-=cost
    pos[s]={'qty':o['qty']*leverage,'price':o['price'],'ts':ts,'entryfee':100*leverage*fee,'funding':0.}
    settle(s,f[s][i],m[s][i,0],ts,True)
    orders.append({**o,'qty':pos[s]['qty'],'cash':cash})
  for s,p in pos.items():
   low=m[s][i,2];collateral=100+p['qty']*(low-p['price'])-p['funding'];notional=p['qty']*low
   ratio=collateral/notional;minimum_ratio=min(minimum_ratio,ratio)
   if ratio<=.07:issues.append({'ts':ts,'symbol':s,'kind':'conservative_liquidation_barrier','collateral_to_notional':ratio})
  for o in stop_events.get(ts+300,[]):close(o)
  equity=cash+sum(100+p['qty']*(m[s][i,3]-p['price'])-p['funding'] for s,p in pos.items())
  gross=sum(p['qty']*m[s][i,3] for s,p in pos.items())/equity
  peak=max(peak,equity);dd=100*(1-equity/peak);maxdd=max(maxdd,dd);mincash=min(mincash,cash);maxgross=max(maxgross,gross);totalexp+=gross
  if (ts+300)%3600==0:curve.append([ts+300,equity,dd,gross])
 for o in final:close(o)
 assert not pos
 error=abs(1000+sum(t['pnl'] for t in trades)-cash);assert error<1e-7
 maxdd=max(maxdd,100*(1-cash/peak));curve[-1]=[int(seconds[-1]+300),cash,100*(1-cash/peak),0.]
 wins=[t['pnl'] for t in trades if t['pnl']>0]
 return {'start':start,'end':end,'fee':fee,'slippage':slip,'delay_minutes':base['delay_minutes'],'resolution':'5m','leverage':leverage,'initial':1000.,'final_equity':cash,'return_pct':(cash/1000-1)*100,'max_drawdown':maxdd,'trade_count':len(trades),'win_rate':len(wins)/len(trades)*100 if trades else 0,'fees':sum(t['fees'] for t in trades),'slippage_cost':sum(t['slippage'] for t in trades),'funding_cost':sum(t['funding'] for t in trades),'contributions':{s:sum(t['pnl'] for t in trades if t['symbol']==s) for s in engine.SYMBOLS},'mean_exposure_pct':totalexp/len(index)*100,'max_exposure_pct':maxgross*100,'minimum_collateral_to_mark_notional_pct':minimum_ratio*100 if trades else None,'free_cash_min':mincash,'constraint_events':issues,'valid_for_comparison':not issues,'ledger_error':error,'top3_profit_share':sum(sorted(wins,reverse=True)[:3])/sum(wins)*100 if wins else None,'trades':trades,'orders':orders,'funding_events':funding_events,'curve':engine.compress_curve(curve)}

def simulate(start,end,mode,leverage=2,fee=.001,delay=0):
 _,m,f=inputs();r=replay(base_run(start,end,mode,fee,delay),m,f,leverage)
 r.update(mode=mode,name=NAMES[mode]);return r

def key(start,end,mode,leverage,fee,delay=0):return f'{start}_{end}_{mode}_L{leverage}_{round(fee*10000)}_d{delay}'

def cached_run(start,end,mode,leverage=2,fee=.001,delay=0):
 ident=key(start,end,mode,leverage,fee,delay);path=ROOT/'results'/(ident+'.json.gz')
 if path.exists():return engine.read(path)
 r=simulate(start,end,mode,leverage,fee,delay);r['id']=ident;engine.dump(path,r);return r
