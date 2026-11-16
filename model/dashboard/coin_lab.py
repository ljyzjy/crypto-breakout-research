"""Independent automatic-universe research endpoints; no trading credentials."""
import sys,csv,io,re,threading,uuid
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse,Response
from pydantic import BaseModel
ROOT=Path(__file__).resolve().parents[1]/'short-term-research/coin-lab-v1'
sys.path.insert(0,str(ROOT))
import coin_engine as c
import automatic_engine as a
OPT=ROOT.parent/'pool-optimization-v1'
sys.path.insert(0,str(OPT))
import pool_engine as pe
NEW_MODES=[m for m in pe.VARIANTS if m!='pool_control']
from performance_metrics import enrich,enrich_many
router=APIRouter();jobs={};lock=threading.Lock();pool=ThreadPoolExecutor(max_workers=1)

def compact(r):return {k:v for k,v in c.summary(r).items() if k!='selection_trace'}

@router.get('/coin-lab')
def page():return FileResponse(Path(__file__).with_name('coin-lab.html'))

@router.get('/api/coin-lab/meta')
def meta():
    manifest=c.base.read(ROOT/'pool-data-manifest.json') if (ROOT/'pool-data-manifest.json').exists() else None
    rows=[]
    for p in ('sizing-metrics.json','automatic-metrics.json'):
        if (ROOT/p).exists():rows+=c.base.read(ROOT/p)
    return {'ready':(ROOT/'execution-manifest.json').exists(),'protocol':c.base.read(ROOT/'automatic-protocol-v2.json'),
            'pool':{'directories':manifest['directory_count'],'symbols':manifest['symbols_with_period_data'],'archives':len(manifest['archives'])} if manifest else None,
            'policies':{**c.POLICIES,**a.AUTO,**pe.VARIANTS},'metrics':enrich_many(rows),
            'assessment':c.base.read(ROOT/'assessment.json') if (ROOT/'assessment.json').exists() else None,
            'optimization':{'diagnosis':c.base.read(OPT/'diagnosis.json'),'protocol':c.base.read(OPT/'protocol.json'),
                            'metrics':enrich_many(c.base.read(OPT/'metrics.json')) if (OPT/'metrics.json').exists() else [],
                            'assessment':c.base.read(OPT/'assessment.json') if (OPT/'assessment.json').exists() else None},
            'min_date':'2025-01-01','max_date':'2026-10-31'}

class Period(BaseModel):
    start:date
    end:date
    universe:Literal['AUTO','BTC_ETH','BTC','ETH']='AUTO'
    fee:Literal[.001,.002,.003]=.001
    resolution:Literal['1h','5m']='5m'
    delay:Literal[0,5]=0

def run_job(key,p):
    try:
        symbols={'AUTO':('BTCUSDT','ETHUSDT'),'BTC_ETH':('BTCUSDT','ETHUSDT'),'BTC':('BTCUSDT',),'ETH':('ETHUSDT',)}[p.universe]
        rows=[];modes=list(c.POLICIES)+(list(a.AUTO)+NEW_MODES if p.universe=='AUTO' else [])
        for i,mode in enumerate(modes):
            if mode in NEW_MODES:r=pe.cached_run(str(p.start),str(p.end),mode,p.fee,p.resolution,p.delay)
            elif mode in a.AUTO:r=a.cached_run(str(p.start),str(p.end),mode,p.fee,p.resolution,p.delay)
            else:r=c.cached_run(str(p.start),str(p.end),mode,p.fee,p.resolution,p.delay,symbols)
            rows.append(compact(r))
            with lock:jobs[key]['progress']=i+1
        with lock:jobs[key].update(status='complete',rows=rows)
    except Exception:
        import traceback;traceback.print_exc()
        with lock:jobs[key].update(status='failed',error='本次回测未完成，已保留原结果；请检查本地日志。')

@router.post('/api/coin-lab/jobs')
def create(p:Period,request:Request):
    if request.headers.get('origin') not in (None,'http://127.0.0.1:8765','http://localhost:8765'):raise HTTPException(403,'只接受本地请求')
    if not date(2025,1,1)<=p.start<=p.end<=date(2026,10,31):raise HTTPException(400,'日期范围为2025-01-01至2026-10-31')
    if p.delay and p.resolution!='5m':raise HTTPException(400,'延迟只用于5分钟执行')
    if p.universe=='AUTO' and not (ROOT/'execution-manifest.json').exists():raise HTTPException(409,'公开币池数据仍在校验')
    key=uuid.uuid4().hex
    with lock:
        if any(j['status']=='running' for j in jobs.values()):raise HTTPException(429,'已有回测正在运行')
        jobs[key]={'id':key,'status':'running','progress':0,'total':14 if p.universe=='AUTO' else 7}
    pool.submit(run_job,key,p)
    return {'id':key}

@router.get('/api/coin-lab/jobs/{key}')
def job(key:str):
    with lock:
        if key not in jobs:raise HTTPException(404,'任务不存在')
        return dict(jobs[key])

def result_data(key):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{10,180}',key):raise HTTPException(400,'结果标识无效')
    p=(OPT if key.endswith('__POOL_OPT1') else ROOT)/'results'/(key+'.json.gz')
    if not p.exists():raise HTTPException(404,'结果尚未计算')
    return enrich(c.base.read(p))

@router.get('/api/coin-lab/results/{key}')
def detail(key:str):
    r=result_data(key);r.pop('orders',None);return r

@router.get('/api/coin-lab/export/{key}')
def export(key:str):
    r=result_data(key);buf=io.StringIO();columns=['symbol','entry_ts','exit_ts','stake','qty','entry_price','exit_price','stop_distance','planned_stop_loss','pnl','fees','slippage','reason']
    writer=csv.DictWriter(buf,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(r['trades'])
    return Response('\ufeff'+buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{key}.csv"'})

@router.get('/api/coin-lab/ranks')
def ranks(day:date=date(2026,10,31)):
    path=ROOT/'daily-ranks.json'
    if not path.exists():raise HTTPException(409,'币池正在准备')
    rows=c.base.read(path);row=next((r for r in rows if r['date']==str(day)),None)
    if row is None:raise HTTPException(400,'日期超出公开币池范围')
    return row

@router.get('/api/coin-lab/evidence/{name}')
def evidence(name:str):
    allowed={'diagnosis.json','baseline_trade_diagnosis.csv','protocol.json','metrics.csv','validation.json','sources.json'}
    if name not in allowed or not (OPT/name).exists():raise HTTPException(404,'该证据尚不可用')
    return FileResponse(OPT/name,filename=name)
