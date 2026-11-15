"""Synthetic checks for trigger order and entry/exit five-second delays."""
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('seconds_exit_test',HERE/'research_seconds_exit.py')
m=importlib.util.module_from_spec(sp);sys.modules[sp.name]=m;sp.loader.exec_module(m)
base=1_700_000_040_000
def archive(lines):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('test.csv','agg_trade_id,price,transact_time\n'+''.join(f'{i},{p},{t}\n' for i,p,t in lines))
    return b.getvalue()
class Response:
    def __init__(self,body,text=''):self.content=body;self.text=text
    def raise_for_status(self):pass
class Session:
    def __init__(self,body):self.body=body
    def get(self,url,timeout=None):
        return Response(b'',hashlib.sha256(self.body).hexdigest()+'  file.zip') if url.endswith('.CHECKSUM') else Response(self.body)
spec={'stop_price':99.5,'level':100.5,'score':1.,'rank':1,'rvol':2.,'liquidity_rank':1}
event={'observation_id':'test','symbol':'BTCUSDT','contract':'BTCUSDT','trigger_minute':base,
       'quarter_start':base,'quarter_end':base+3*m.M,'upper':100.5,'lower':95.,'atr':2.,
       'long_known_eligible':True,'short_known_eligible':False,'long_spec':json.dumps(spec),'short_spec':'null'}
def run(lines):
    body=archive(lines);m.session=lambda:Session(body)
    result=m.task(('BTCUSDT','2026-05-01',[event]));assert result['status']=='verified'
    return result['rows'][0]

# A target crosses at +8s; the market-exit reference is the first trade after +13s.
target=[(1,100.6,base+1000),(2,100.6,base+6000),(3,102.,base+8000),
        (4,101.5,base+13_001),(5,101.4,base+90_000)]
x=run(target)
assert x['status']=='verified' and x['entry_ts']==base+6000
assert x['h15_exit_reason']=='target' and x['h15_exit_signal_ts']==base+8000
assert x['h15_exit_ts']==base+13_001 and x['h15_exit_raw']==101.5
# A gap below the stop is exited at the later observed price, not at the stop.
stop=[(1,100.6,base+1000),(2,100.6,base+6000),(3,99.4,base+8000),
      (4,98.,base+13_001),(5,98.,base+90_000)]
x=run(stop)
assert x['status']=='verified' and x['h30_exit_reason']=='stop' and x['h30_exit_raw']==98.
# No barrier: a 15s timer sends exit at entry+15s and references a trade 5s later.
timer=[(1,100.6,base+1000),(2,100.6,base+6000),(3,100.7,base+26_001),
       (4,100.7,base+41_001),(5,100.7,base+71_001)]
x=run(timer)
assert x['status']=='verified' and x['h15_exit_reason']=='time'
assert x['h15_exit_signal_ts']==base+21_000 and x['h15_exit_ts']==base+26_001
missing=run([(1,100.6,base+1000),(2,100.6,base+6000)])
assert missing['status']=='no_exit_reference'
event.update(upper=105.,lower=99.,long_known_eligible=False,short_known_eligible=True,
             short_spec=json.dumps({**spec,'stop_price':100.,'level':99.}))
short=[(1,98.9,base+1000),(2,98.9,base+6000),(3,97.6,base+8000),
       (4,98.,base+13_001),(5,98.,base+90_000)]
x=run(short)
assert x['status']=='verified' and x['side']==-1 and x['h15_exit_reason']=='target'
assert x['h15_exit_ts']==base+13_001 and x['h15_exit_raw']==98.
report={'five_second_entry_delay':True,'five_second_exit_delay':True,'stop_gap_uses_later_trade':True,
        'time_exit_has_delivery_delay':True,'short_trigger_and_exit':True,'missing_exit_is_not_invented':True}
(HERE/'秒级退出合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('SECOND_EXIT_SYNTHETICS_PASS',json.dumps(report),flush=True)
