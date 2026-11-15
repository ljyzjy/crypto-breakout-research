"""Research-only long/short factor dashboard; no execution account mutations."""
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
import sys,threading,uuid,re,csv,io
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse,Response
from pydantic import BaseModel,Field
ROOT=Path(__file__).resolve().parents[1]/'short-term-research/short-factor-v1'
sys.path.insert(0,str(ROOT));import factor_engine as e
router=APIRouter();pool=ThreadPoolExecutor(max_workers=1);lock=threading.Lock();jobs={}
@router.get('/short-factor')
def page():return FileResponse(Path(__file__).with_name('short-factor.html'))
@router.get('/api/short-factor/meta')
def meta():return {'names':e.NAMES,'protocol':e.base.read(ROOT/'protocol.json'),'sources':e.base.read(ROOT/'sources.json'),'metrics':e.base.read(ROOT/'metrics.json'),'assessment':e.base.read(ROOT/'assessment.json'),'diagnostics':e.base.read(ROOT/'factor-diagnostics.json')}
class Period(BaseModel):
    start:date
    end:date
    leverage:int=Field(default=1,ge=1,le=10)
    fee:Literal[.001,.002,.003]=.001
    delay:Literal[0,5]=0
def work(key,p):
    try:
        rows=[]
        for mode in e.NAMES:
            rows.append(e.summary(e.cached_run(str(p.start),str(p.end),mode,p.leverage,p.fee,p.delay)))
            with lock:jobs[key]['progress']=len(rows)
        with lock:jobs[key].update(status='complete',rows=rows)
    except Exception:
        import traceback;traceback.print_exc()
        with lock:jobs[key].update(status='failed',error='计算失败，请检查研究日志；当前模拟未修改。')
@router.post('/api/short-factor/jobs')
def create(p:Period,request:Request):
    if request.headers.get('origin') not in (None,'http://127.0.0.1:8765','http://localhost:8765'):raise HTTPException(403,'仅限本地请求')
    if not date(2025,1,1)<=p.start<=p.end<=date(2026,10,31):raise HTTPException(400,'日期范围2025-01-01至2026-10-31')
    key=uuid.uuid4().hex
    with lock:
        if any(j['status']=='running' for j in jobs.values()):raise HTTPException(429,'已有回测正在计算')
        jobs[key]={'id':key,'status':'running','progress':0,'total':4}
    pool.submit(work,key,p);return {'id':key}
@router.get('/api/short-factor/jobs/{key}')
def job(key:str):
    with lock:
        if key not in jobs:raise HTTPException(404,'任务不存在')
        return dict(jobs[key])
def result(key):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{10,150}',key):raise HTTPException(400,'编号无效')
    p=ROOT/'results'/(key+'.json.gz')
    if not p.exists():raise HTTPException(404,'结果未计算')
    return e.base.read(p)
@router.get('/api/short-factor/results/{key}')
def detail(key:str):
    r=result(key);r.pop('orders',None);r.pop('selection_trace',None);return r
@router.get('/api/short-factor/export/{key}')
def export(key:str):
    r=result(key);buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=['symbol','direction','entry_ts','exit_ts','margin','notional','entry_price','exit_price','pnl','fees','slippage','funding','reason'],extrasaction='ignore');w.writeheader();w.writerows(r['trades'])
    return Response('\ufeff'+buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{key}.csv"'})
@router.get('/api/short-factor/evidence/{name}')
def evidence(name:str):
    if name not in {'protocol.json','sources.json','metrics.csv','assessment.json','validation.json','factor-diagnostics.json','factor-values.csv.gz','多空与流动性反转因子报告.txt'} or not (ROOT/name).exists():raise HTTPException(404,'证据不可用')
    return FileResponse(ROOT/name,filename=name)
