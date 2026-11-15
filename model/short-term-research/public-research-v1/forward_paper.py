"""Independent prospective spot paper portfolios, public market data only.

Uses observable bid/ask at polling time, not reconstructed past fills. Never opens
an exchange account, reads credentials, or writes the existing Freqtrade database.
"""
from pathlib import Path
import hashlib,json,os,time,urllib.parse,urllib.request
import pandas as pd
import public_engine as p

ROOT=p.ROOT/'forward';STATE=ROOT/'state.json';MODES=('DailyMomentum',*p.VARIANTS)
BASE='https://data-api.binance.vision/api/v3/'

def get(endpoint,params=None):
 url=BASE+endpoint+('?' +urllib.parse.urlencode(params) if params else '')
 with urllib.request.urlopen(url,timeout=15) as r:return json.loads(r.read())

def fresh_state(now):
 return {'started_utc':pd.Timestamp(now,unit='s',tz='UTC').isoformat(),'started_ts':now,'status':'starting','mode':'independent_spot_paper','leverage':1,'poll_seconds':30,'last_update_utc':None,'selected_candidate':'multi_momentum','selection_note':'Lowest drawdown of two historical gate passers; does not outperform original DailyMomentum. All three candidates and baseline observed together.','portfolios':{m:{'initial':1000.,'cash':1000.,'positions':{},'orders':[],'trades':[],'curve':[],'peak':1000.,'max_drawdown':0.,'cooldown':{},'stops':[],'guard_until':0,'last_decision_hour':None,'equity':1000.,'return_pct':0.} for m in MODES},'execution_note':'Public bid/ask observed every30s plus .05% adverse slip and .1% fee each side; stops checked on observed bid, so between-poll touches can be missed. Never backfill missed paper fills. Device/process must remain running.'}

def step(state,now,quotes,signals,source_hour):
 fee=.001;slip=.0005
 for mode,a in state['portfolios'].items():
  def close(s,reason):
   pos=a['positions'].pop(s);fill=quotes[s]['bid']*(1-slip);exitfee=pos['qty']*fill*fee
   proceeds=pos['qty']*fill-exitfee;net=proceeds-pos['cost'];a['cash']+=proceeds
   a['trades'].append({'symbol':s,'entry_ts':pos['entry_ts'],'exit_ts':now,'entry_price':pos['price'],'exit_price':fill,'qty':pos['qty'],'pnl':net,'fees':pos['entry_fee']+exitfee,'reason':reason})
   a['orders'].append({'side':'sell','symbol':s,'ts':now,'price':fill,'qty':pos['qty'],'reason':reason})
   a['cooldown'][s]=now+6*3600
   if reason=='stop_loss' and net<0:
    a['stops']=[t for t in a['stops'] if t>=now-48*3600]+[now]
    if len(a['stops'])>=2:a['guard_until']=now+24*3600
  for s in list(a['positions']):
   if quotes[s]['bid']<=a['positions'][s]['stop']:close(s,'stop_loss')
  # Accept only newly observed signals whose information became available after launch.
  information_ts=source_hour+3600
  if a['last_decision_hour']!=source_hour and state['started_ts']<=information_ts<=now:
   a['last_decision_hour']=source_hour
   for s in list(a['positions']):
    if signals[mode][s][1]:close(s,'signal_exit')
   for s in p.engine.SYMBOLS:
    buy,sell=signals[mode][s]
    if not buy or sell or s in a['positions'] or now<a['cooldown'].get(s,0) or now<a['guard_until']:continue
    if len(a['positions'])>=2 or a['cash']<100.1:continue
    fill=quotes[s]['ask']*(1+slip);qty=100/fill;a['cash']-=100.1
    a['positions'][s]={'entry_ts':now,'price':fill,'qty':qty,'cost':100.1,'entry_fee':.1,'stop':fill*.96,'information_ts':information_ts}
    a['orders'].append({'side':'buy','symbol':s,'ts':now,'information_ts':information_ts,'price':fill,'qty':qty,'reason':'entry'})
  a['equity']=a['cash']+sum(pos['qty']*quotes[s]['bid'] for s,pos in a['positions'].items())
  a['peak']=max(a['peak'],a['equity']);dd=100*(1-a['equity']/a['peak']);a['max_drawdown']=max(a['max_drawdown'],dd)
  a['return_pct']=100*(a['equity']/1000-1)
  point=[now,a['equity'],dd]
  if a['curve'] and a['curve'][-1][0]//3600==now//3600:a['curve'][-1]=point
  else:a['curve'].append(point)
  assert a['cash']>=-1e-8
 state.update(status='running',last_update_utc=pd.Timestamp(now,unit='s',tz='UTC').isoformat(),last_source_close_utc=pd.Timestamp(source_hour+3600,unit='s',tz='UTC').isoformat(),error=None)

def refresh(history,now):
 for s in p.engine.SYMBOLS:
  d=history[(s,'1h')]
  begin=int((d.index[-1]+pd.Timedelta(hours=1)).timestamp()*1000)
  parts=[]
  while begin<now*1000:
   rows=get('klines',{'symbol':s,'interval':'1h','startTime':begin,'limit':1000})
   if not rows:break
   x=pd.DataFrame(rows)
   x=x[pd.to_numeric(x[6])<now*1000]
   if x.empty:break
   x=x.rename(columns={1:'open',2:'high',3:'low',4:'close',5:'volume',7:'quote_volume',8:'trades',10:'buy_quote'})
   x.index=pd.to_datetime(x[0],unit='ms',utc=True);x=x[list(d.columns)].astype(float);parts.append(x)
   begin=int((x.index[-1]+pd.Timedelta(hours=1)).timestamp()*1000)
   if len(rows)<1000:break
  if parts:
   d=pd.concat([d,*parts]).sort_index();assert not d.index.duplicated().any();history[(s,'1h')]=d
   d.to_parquet(ROOT/f'{s}-history.parquet')
 return history

def run(once=False):
 ROOT.mkdir(exist_ok=True)
 # One Windows observer owns this independent state at a time.
 import msvcrt
 lock=open(ROOT/'observer.lock','a+b')
 lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
 try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:raise RuntimeError('An independent observer is already running')
 from run_public import freeze
 freeze()
 history={k:v.copy() for k,v in p.engine.inputs()[0].items() if k[1]=='1h'}
 for s in p.engine.SYMBOLS:
  path=ROOT/f'{s}-history.parquet'
  if path.exists():history[(s,'1h')]=pd.read_parquet(path)
 now=int(time.time());state=p.engine.read(STATE) if STATE.exists() else fresh_state(now)
 state['process']={'pid':os.getpid(),'started_at':now}
 state['source_hashes']={n:hashlib.sha256((p.ROOT/n).read_bytes()).hexdigest() for n in ['public_engine.py','protocol.json','forward_paper.py']}
 p.engine.dump(STATE,state);cached_hour=None;signal=None
 while True:
  try:
   now=int(get('time')['serverTime']//1000)
   if cached_hour!=now//3600:
    refresh(history,now)
    source=min(d.index[-1] for d in history.values());source_ts=int(source.timestamp())
    if now-source_ts>2*3600:raise ValueError('Public hourly data stale; no new orders')
    allframes={'DailyMomentum':{s:p.engine.features(history[(s,'1h')]) for s in p.engine.SYMBOLS}}
    allframes.update({m:p.signal_frames(history,m) for m in p.VARIANTS})
    signal={m:{s:tuple(bool(v) for v in frames[s].loc[source,['DailyMomentum_buy','DailyMomentum_sell']]) for s in p.engine.SYMBOLS} for m,frames in allframes.items()}
    cached_hour=now//3600
   quotes={}
   for s in p.engine.SYMBOLS:
    q=get('ticker/bookTicker',{'symbol':s});quotes[s]={'bid':float(q['bidPrice']),'ask':float(q['askPrice'])}
    assert 0<quotes[s]['bid']<=quotes[s]['ask']
   step(state,int(time.time()),quotes,signal,source_ts);state['quotes']=quotes
  except Exception as e:
   state.update(status='waiting_for_public_data',error=type(e).__name__+': '+str(e)[:160],last_poll_utc=pd.Timestamp.now(tz='UTC').isoformat())
  p.engine.dump(STATE,state)
  if once:return state
  time.sleep(30)

if __name__=='__main__':run('--once' in __import__('sys').argv)
