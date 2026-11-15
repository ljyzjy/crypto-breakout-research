"""Synthetic dual-boundary ordering and 5s archival extraction tests."""
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('touch_extract_test',HERE/'extract_touch_trades.py')
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
        return Response(b'',hashlib.sha256(self.body).hexdigest()+'  test.zip') if url.endswith('.CHECKSUM') else Response(self.body)
specrow={'stop_price':100.,'level':101.,'score':1.,'rank':1,'rvol':2.,'liquidity_rank':1}
event={'observation_id':'synthetic','symbol':'BTCUSDT','contract':'BTCUSDT','day':'2024-01-01','source_year':'2024',
       'trigger_minute':base,'quarter_start':base,'quarter_end':base+3*m.M,
       'upper':101.,'lower':99.,'atr':2.,'long_known_eligible':True,'short_known_eligible':False,
       'long_spec':json.dumps(specrow),'short_spec':json.dumps({**specrow,'stop_price':102.,'level':99.})}
def run(e,lines):
    body=archive(lines);m.session=lambda:Session(body)
    result=m.task(('BTCUSDT','2024-01-01',[e]));assert result['status']=='verified'
    return result['rows'][0]

both=[(1,100.,base+1000),(2,98.8,base+2000),(3,101.2,base+3000),
      (4,99.2,base+7001),(5,99.1,base+10_000)]
x=run(event,both);assert x['status']=='first_direction_ineligible'
x=run({**event,'short_known_eligible':True},both)
assert x['status']=='verified' and x['side']==-1 and x['decision_ts']==base+2000
assert x['entry_exec_ts']==base+7001 and x['raw_entry_5s']==99.2
cross=[(1,100.,base+1000),(2,101.2,base+58_000),(3,101.5,base+63_001),
       (4,101.9,base+64_000),(5,101.3,base+70_000)]
x=run(event,cross)
assert x['status']=='verified' and x['decision_ts']==base+58_000 and x['entry_exec_ts']==base+63_001
assert x['ts']==base+m.M and x['suffix_high']==101.9 and x['suffix_low']==101.3
empty=run(event,[(1,101.2,base+10_000)])
assert empty['status']=='no_price_reference'
report={'first_cross_direction_has_priority':True,'ineligible_first_cross_never_replaced':True,
        'five_second_delay_after_actual_cross':True,'entry_can_cross_minute':True,
        'post_entry_extrema_only':True,'missing_reference_is_not_silently_filled':True}
(HERE/'首次触价提取合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TOUCH_EXTRACTOR_SYNTHETICS_PASS',json.dumps(report),flush=True)
