import hashlib,time
import pandas as pd
import public_engine as p
from public_engine import ROOT,RESEARCH,engine
from st_study import freeze as old_freeze,summary

def freeze():
 payload={'original':old_freeze(),'new':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['public_engine.py','protocol.json','test_public.py','run_public.py']}}
 file=ROOT/'frozen.json'
 if file.exists():
  expected=engine.read(file)['hashes']
  amendments=engine.read(ROOT/'reporting_amendments.json') if (ROOT/'reporting_amendments.json').exists() else []
  for a in amendments:
   assert expected['new'][a['file']]==a['before']
   expected['new'][a['file']]=a['after']
  assert expected==payload,'Frozen source changed'
 else:engine.dump(file,{'hashes':payload,'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'before_new_outcomes':True})
 return payload

def matrix():
 windows=engine.read(RESEARCH/'protocol.json')['windows']
 for res,keys,fees,delay in [('1h',list(windows),[.001,.002,.003],0),('5m',['later','2025','2026'],[.001,.002,.003],0),('5m',['later'],[.001],5)]:
  for window in keys:
   for fee in fees:
    for variant in p.VARIANTS:yield window,*windows[window],variant,fee,res,delay

def decisions(metrics):
 def get(v,w,f=.001,r='1h',d=0):return next(x for x in metrics if (x['mode'],x['window'],x['fee'],x['resolution'],x['delay_minutes'])==(v,w,f,r,d))
 results=[]
 for v in p.VARIANTS:
  a=get(v,'later');b=get(v,'later',r='5m');c=get(v,'later',r='5m',d=5)
  gates={'later_net_positive':a['return_pct']>0,'2025_positive':get(v,'2025')['return_pct']>0,'2026_positive':get(v,'2026')['return_pct']>0,'later_30_trades':a['trade_count']>=30,'double_cost_positive':get(v,'later',.002)['return_pct']>0,'five_minute_positive':b['return_pct']>0,'delayed_positive':c['return_pct']>0,'later_no_missing_held_prices':all(x['valid_for_comparison'] for x in [a,b,c])}
  gates={k:bool(value) for k,value in gates.items()}
  results.append({'mode':v,'name':p.VARIANTS[v]['name'],'gates':gates,'passes':all(gates.values()),'both_coins_positive':all(x>0 for x in a['contributions'].values()),'top3_profit_share':a['top3_profit_share']})
 return results

def check(r):
 fs=p.cached_signals(r['mode'])
 for x in r['orders']:
  if x['side']=='buy':
   assert x['information_ts']==x['ts']-r['delay_minutes']*60
   t=pd.Timestamp(x['information_ts'],unit='s',tz='UTC')-pd.Timedelta(hours=1)
   assert fs[x['symbol']].loc[t,'DailyMomentum_buy'] and not fs[x['symbol']].loc[t,'DailyMomentum_sell']
   assert abs(x['qty']*x['price']-100)<1e-8
 assert r['open_positions']==0 and r['cash_min']>=0 and r['ledger_error']<1e-7
 assert abs(sum(t['pnl'] for t in r['trades'])-(r['final_equity']-1000))<1e-7

def run():
 start=time.time();before=freeze()
 from test_public import validate
 validation=validate();engine.dump(ROOT/'validation.json',validation);print('Validation PASS; sources frozen',flush=True)
 rows=[]
 for i,(window,a,b,v,f,res,d) in enumerate(matrix()):
  r=p.cached_run(a,b,v,f,res,d);check(r);row=summary(r);row['window']=window;rows.append(row)
  if (i+1)%9==0:print(f'{i+1}/93 complete ({time.time()-start:.1f}s)',flush=True)
 assert len(rows)==93 and before==freeze()
 engine.dump(ROOT/'metrics.json',rows);pd.json_normalize(rows).drop(columns=['data_issues']).to_csv(ROOT/'metrics.csv',index=False,encoding='utf-8-sig')
 choice=decisions(rows);engine.dump(ROOT/'decision.json',choice)
 engine.dump(ROOT/'verification.json',{'status':'PASS','registered_runs':len(rows),'sources_unchanged':True,'all_entries_past_only':True,'ledgers_reconciled':True,'invalid_scenarios':sum(not r['valid_for_comparison'] for r in rows),'validation':validation,'elapsed_seconds':time.time()-start})
 print(pd.DataFrame([r for r in rows if r['window']=='later' and r['fee']==.001 and r['resolution']=='1h'])[['mode','return_pct','max_drawdown','trade_count','contributions']].to_string(index=False))
 print(choice)

if __name__=='__main__':run()
