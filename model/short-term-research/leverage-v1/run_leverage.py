import hashlib,time
import pandas as pd
import leverage_engine as l
from leverage_engine import ROOT,engine

def freeze():
 from run_public import freeze as previous_freeze
 files=['protocol.json','leverage_engine.py','test_leverage.py','run_leverage.py','download_data.py','data-manifest.json']
 hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
 payload={'previous':previous_freeze(),'files':hashes}
 file=ROOT/'frozen.json'
 if file.exists():assert engine.read(file)['hashes']==payload
 else:engine.dump(file,{'hashes':payload,'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'before_futures_outcomes':True})
 return payload

def run():
 before=freeze();start=time.time()
 from test_leverage import validate
 validation=validate();engine.dump(ROOT/'validation.json',validation);print('Perpetual accounting validation PASS',flush=True)
 protocol=engine.read(ROOT/'protocol.json');matrix=[]
 for w,(a,b) in protocol['windows'].items():
  for mode in l.MODES:
   for fee in [.001,.002,.003]:
    for L in [1,2,3]:matrix.append((w,a,b,mode,L,fee,0))
 a,b=protocol['windows']['later']
 for mode in l.MODES:
  for L in [1,2,3]:matrix.append(('later',a,b,mode,L,.001,5))
 rows=[]
 for i,(w,a,b,m,L,f,d) in enumerate(matrix):
  r=l.cached_run(a,b,m,L,f,d);row={k:v for k,v in r.items() if k not in ['trades','orders','curve','funding_events']};row['window']=w;rows.append(row)
  if (i+1)%12==0:print(f'{i+1}/120 futures scenarios complete ({time.time()-start:.1f}s)',flush=True)
 assert len(rows)==120 and before==freeze()
 engine.dump(ROOT/'metrics.json',rows);pd.json_normalize(rows).to_csv(ROOT/'metrics.csv',index=False,encoding='utf-8-sig')
 engine.dump(ROOT/'verification.json',{'status':'PASS','registered_runs':120,'validation':validation,'source_hashes_unchanged':True,'invalid_scenarios':sum(not r['valid_for_comparison'] for r in rows),'elapsed_seconds':time.time()-start})
 print(pd.DataFrame([r for r in rows if r['window']=='later' and r['fee']==.001 and r['delay_minutes']==0])[['mode','leverage','return_pct','max_drawdown','funding_cost','valid_for_comparison']].to_string(index=False))

if __name__=='__main__':run()
