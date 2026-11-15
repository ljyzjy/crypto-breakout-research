import hashlib,time
import pandas as pd
import risk_engine as r
from risk_engine import ROOT,RESEARCH,engine
from st_study import summary,freeze as original_freeze

def freeze():
 files=['risk_engine.py','run_risk.py','test_risk.py','protocol.json','execution-provenance.txt']
 payload={'previous':original_freeze(),'files':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}}
 path=ROOT/'frozen.json'
 if path.exists():assert engine.read(path)['hashes']==payload,'Frozen risk inputs changed'
 else:engine.dump(path,{'hashes':payload,'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'before_risk_outcomes':True})
 return payload

def matrix():
 w=engine.read(RESEARCH/'protocol.json')['windows']
 for res,keys,fees,delay in [('1h',list(w),[.001,.002,.003],0),('5m',['later','2025','2026'],[.001,.002,.003],0),('5m',['later'],[.001],5)]:
  for window in keys:
   for f in fees:
    for p in r.POLICIES:yield window,*w[window],p,f,res,delay

def check(result):
 sizes=r.sizing_frames(r.inputs()[0],result['mode']);held={}
 for o in result['orders']:
  if o['side']=='buy':
   source=pd.Timestamp(o['information_ts'],unit='s',tz='UTC')-pd.Timedelta(hours=1)
   assert o['information_ts']==o['ts']-result['delay_minutes']*60
   target=float(sizes[o['symbol']].loc[source])
   if result['mode']=='inverse_vol_pair':target=min(target,max(0.,200-sum(held.values())))
   stake=o['qty']*o['price'];assert abs(stake-target)<1e-7 and stake>=10-1e-7
   held[o['symbol']]=stake
   cap=400 if result['mode'] in ['fixed200','vol_target200'] else 200
   assert sum(held.values())<=cap+1e-7
  else:held.pop(o['symbol'])
 assert not held and result['open_positions']==0 and result['cash_min']>=0 and result['ledger_error']<1e-7
 assert abs(sum(t['pnl'] for t in result['trades'])+1000-result['final_equity'])<1e-7
 for t in result['trades']:assert abs(t['gross_pnl']-t['fees']-t['slippage']-t['pnl'])<1e-8

def decisions(rows):
 def get(m,w='later',f=.001,res='1h',d=0):return next(x for x in rows if (x['mode'],x['window'],x['fee'],x['resolution'],x['delay_minutes'])==(m,w,f,res,d))
 base=get('fixed100');out=[]
 for m,v in r.POLICIES.items():
  if not v['candidate']:continue
  a=get(m);b=get(m,res='5m');c=get(m,res='5m',d=5)
  gates={'later_net_positive':a['return_pct']>0,'2025_positive':get(m,'2025')['return_pct']>0,'2026_positive':get(m,'2026')['return_pct']>0,'later_30_trades':a['trade_count']>=30,'double_cost_positive':get(m,f=.002)['return_pct']>0,'five_minute_positive':b['return_pct']>0,'delayed_positive':c['return_pct']>0,'later_no_missing_held_prices':all(x['valid_for_comparison'] for x in [a,b,c])}
  gates={k:bool(v) for k,v in gates.items()};improved=bool(a['return_pct']>=base['return_pct'] and a['max_drawdown']<=base['max_drawdown'] and (a['return_pct']>base['return_pct'] or a['max_drawdown']<base['max_drawdown']))
  out.append({'mode':m,'name':v['name'],'gates':gates,'passes':all(gates.values()),'strict_improvement_vs_fixed100':improved,'qualifies_new_forward':all(gates.values()) and improved})
 return out

def main():
 before=freeze();start=time.time()
 from test_risk import validate
 validation=validate();engine.dump(ROOT/'validation.json',validation);print('Causal sizing and exact original replay PASS; inputs frozen',flush=True)
 rows=[]
 for i,(w,a,b,p,f,res,d) in enumerate(matrix()):
  result=r.cached_run(a,b,p,f,res,d);check(result);row=summary(result);row['window']=w;rows.append(row)
  if (i+1)%15==0:print(f'{i+1}/155 risk scenarios complete ({time.time()-start:.1f}s)',flush=True)
 assert len(rows)==155 and freeze()==before
 engine.dump(ROOT/'metrics.json',rows);pd.json_normalize(rows).drop(columns=['data_issues']).to_csv(ROOT/'metrics.csv',index=False,encoding='utf-8-sig')
 decision=decisions(rows);engine.dump(ROOT/'decision.json',decision)
 engine.dump(ROOT/'verification.json',{'status':'PASS','registered_runs':155,'validation':validation,'all_sizing_past_only':True,'cash_and_per_coin_portfolio_caps_verified':True,'all_ledgers_reconciled':True,'source_hashes_unchanged':True,'invalid_scenarios':sum(not a['valid_for_comparison'] for a in rows),'elapsed_seconds':time.time()-start})
 print(pd.DataFrame([a for a in rows if a['window']=='later' and a['fee']==.001 and a['resolution']=='1h'])[['mode','return_pct','max_drawdown','trade_count','mean_exposure_pct','contributions']].to_string(index=False))
 print(decision)

if __name__=='__main__':main()
