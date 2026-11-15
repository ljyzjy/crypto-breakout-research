import pandas as pd
import numpy as np
import leverage_engine as l

def validate():
 data,marks,funding=l.inputs()
 # No funding and trade-price mark: the 1x derivative ledger must match funded spot economics.
 base=l.base_run('2025-01-01','2025-03-31','DailyMomentum',.001,0)
 zero={s:pd.Series(dtype=float,index=pd.DatetimeIndex([],tz='UTC')) for s in l.engine.SYMBOLS}
 trade_marks={s:data[(s,'5m')][['open','high','low','close']] for s in l.engine.SYMBOLS}
 replay=l.replay(base,trade_marks,zero,1)
 assert abs(base['final_equity']-replay['final_equity'])<1e-7
 assert abs(base['max_drawdown']-replay['max_drawdown'])<1e-7
 assert len(base['trades'])==len(replay['trades'])
 for a,b in zip(base['trades'],replay['trades']):assert abs(a['pnl']-b['pnl'])<1e-7
 # Every economic change must reconcile to scaled trading P&L less signed actual funding.
 for L in (1,2,3):
  r=l.replay(base,marks,funding,L)
  assert abs((r['final_equity']-1000)-(L*(base['final_equity']-1000)-r['funding_cost']))<1e-7
  assert abs(sum(e['payment'] for e in r['funding_events'])-r['funding_cost'])<1e-7
  assert not r['constraint_events']
 # Inject a 90% mark crash, preserving trade prices: liquidation risk must be detected.
 bad={s:d.copy() for s,d in marks.items()}
 buy=next(x for x in base['orders'] if x['side']=='buy')
 t=pd.Timestamp(buy['ts'],unit='s',tz='UTC');bad[buy['symbol']].loc[t,'low']=buy['price']*.1
 assert not l.replay(base,bad,zero,2)['valid_for_comparison']
 return {'status':'PASS','checks':['1x no-funding ledger and mark drawdown reproduce frozen engine','1/2/3x P&L reconciles to scaled price path minus actual signed funding','funding event totals reconcile','synthetic mark-only crash triggers liquidation barrier']}
