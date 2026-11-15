"""Read-only research results and bounded, independent date-range backtests."""
import csv,io,json,re,sys,threading,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse,Response
from pydantic import BaseModel

RESEARCH=Path(__file__).resolve().parents[1]/'short-term-research'
if str(RESEARCH) not in sys.path:sys.path.insert(0,str(RESEARCH))
from st_engine import MODES,NAMES,read,cached_run,scenario_id
from st_study import summary as raw_summary,freeze
from performance_metrics import enrich,enrich_many
def summary(r):return enrich(raw_summary(r))
OPTIMIZATION=RESEARCH/'optimization-v1'
if str(OPTIMIZATION) not in sys.path:sys.path.insert(0,str(OPTIMIZATION))
from opt_engine import VARIANTS,cached_run as optimized_run
from run_optimization import freeze as optimization_freeze
PUBLIC=RESEARCH/'public-research-v1'
if str(PUBLIC) not in sys.path:sys.path.insert(0,str(PUBLIC))
from public_engine import VARIANTS as PUBLIC_VARIANTS,cached_run as public_run
from run_public import freeze as public_freeze
RISK=RESEARCH/'risk-budget-v1'
if str(RISK) not in sys.path:sys.path.insert(0,str(RISK))
from risk_engine import POLICIES,cached_run as risk_run
from run_risk import freeze as risk_freeze
MODES=(*MODES,*VARIANTS,*PUBLIC_VARIANTS,*POLICIES)
NAMES={**NAMES,**{k:v['name'] for k,v in {**VARIANTS,**PUBLIC_VARIANTS,**POLICIES}.items()}}

router=APIRouter();mutex=threading.Lock();jobs={};pool=ThreadPoolExecutor(max_workers=1)
PATTERN=re.compile(r'^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_(?P<mode>'+ '|'.join(re.escape(m) for m in MODES)+r')_(10|20|30)_(1h|5m)_d(0|5)$')

def result_path(start,end,mode,fee,resolution,delay):
    root=RISK if mode in POLICIES else PUBLIC if mode in PUBLIC_VARIANTS else OPTIMIZATION if mode in VARIANTS else RESEARCH
    return root/'results'/(scenario_id(start,end,mode,fee,resolution,delay)+'.json.gz')

def all_metrics():return enrich_many(read(RESEARCH/'metrics.json')+read(OPTIMIZATION/'metrics.json')+read(PUBLIC/'metrics.json')+read(RISK/'metrics.json'))


@router.get('/short-term')
def page():return FileResponse(Path(__file__).with_name('short-term.html'))


@router.get('/api/short-term/meta')
def meta():
    protocol=read(RESEARCH/'protocol.json');factors=read(RESEARCH/'factors.json')
    factors.pop('thresholds',None)
    return {'windows':protocol['windows'],'names':NAMES,'modes':MODES,
            'decisions':read(RESEARCH/'decision.json'),'verification':read(RESEARCH/'verification.json'),
            'factors':factors,'metrics':all_metrics(),
            'optimization':{'variants':VARIANTS,'decisions':read(OPTIMIZATION/'decision.json'),
                            'verification':read(OPTIMIZATION/'verification.json')},
            'public_research':{'variants':PUBLIC_VARIANTS,'decisions':read(PUBLIC/'decision.json'),'verification':read(PUBLIC/'verification.json')},
            'risk_budget':{'policies':POLICIES,'decisions':read(RISK/'decision.json'),'verification':read(RISK/'verification.json')},
            'min_date':'2023-01-01','min_detail_date':'2025-01-01','max_date':'2026-10-31'}


class Period(BaseModel):
    start:date
    end:date
    fee:Literal[.001,.002,.003]=.001
    resolution:Literal['1h','5m']='1h'
    delay:Literal[0,5]=0


def run_job(key,period):
    try:
        freeze();optimization_freeze();public_freeze();risk_freeze()
        rows=[]
        for i,mode in enumerate(MODES):
            runner=risk_run if mode in POLICIES else public_run if mode in PUBLIC_VARIANTS else optimized_run if mode in VARIANTS else cached_run
            rows.append(summary(runner(period.start.isoformat(),period.end.isoformat(),mode,period.fee,period.resolution,period.delay)))
            with mutex:jobs[key]['progress']=i+1
        with mutex:jobs[key].update(status='complete',rows=rows)
    except Exception:
        import traceback
        traceback.print_exc()
        with mutex:jobs[key].update(status='failed',error='回测未完成，请检查本地研究日志。已有结果保持不变。')


@router.post('/api/short-term/jobs')
def create(period:Period,request:Request):
    if request.headers.get('origin') not in (None,'http://127.0.0.1:8765','http://localhost:8765'):
        raise HTTPException(403,'只接受本地看板请求')
    minimum=date(2025,1,1) if period.resolution=='5m' else date(2023,1,1)
    if not minimum<=period.start<=period.end<=date(2026,10,31):raise HTTPException(400,f'该执行粒度的有效范围：{minimum} 至 2026-10-31')
    if period.delay and period.resolution!='5m':raise HTTPException(400,'5 分钟延迟仅适用于 5 分钟细化执行')
    start,end=period.start.isoformat(),period.end.isoformat()
    paths=[result_path(start,end,m,period.fee,period.resolution,period.delay) for m in MODES]
    key=uuid.uuid4().hex
    with mutex:
        if all(p.exists() for p in paths):
            jobs[key]={'id':key,'status':'complete','progress':len(MODES),'rows':[summary(read(p)) for p in paths]}
        else:
            if any(j['status']=='running' for j in jobs.values()):raise HTTPException(429,'另一个区间正在回测，请稍后再试')
            jobs[key]={'id':key,'status':'running','progress':0}
            pool.submit(run_job,key,period)
    return {'id':key}


@router.get('/api/short-term/jobs/{key}')
def job(key:str):
    with mutex:
        if key not in jobs:raise HTTPException(404,'未找到该回测任务')
        return dict(jobs[key])


def result_file(key):
    match=PATTERN.fullmatch(key)
    if not match:raise HTTPException(400,'无效结果标识')
    mode=match.group('mode')
    root=RISK if mode in POLICIES else PUBLIC if mode in PUBLIC_VARIANTS else OPTIMIZATION if mode in VARIANTS else RESEARCH
    path=root/'results'/(key+'.json.gz')
    if not path.exists():raise HTTPException(404,'该结果尚未计算')
    return path


@router.get('/api/short-term/results/{key}')
def result(key:str):
    data=read(result_file(key));data.pop('orders',None);return enrich(data)


@router.get('/api/short-term/trades/{key}')
def export(key:str):
    data=read(result_file(key));buffer=io.StringIO()
    columns=['symbol','entry_ts','exit_ts','entry_price','exit_price','qty','pnl','return_pct','fees','slippage','gross_pnl','hold_hours','reason']
    writer=csv.DictWriter(buffer,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(data['trades'])
    return Response('\ufeff'+buffer.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="short-term-{key}.csv"'})


@router.get('/api/short-term/metrics.csv')
def metrics_export():
    data=all_metrics();buffer=io.StringIO()
    fields=list(dict.fromkeys(k for row in data for k in row))
    writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader()
    writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in data)
    return Response('\ufeff'+buffer.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="short-term-all-{len(data)}-scenarios.csv"'})


@router.get('/api/short-term/factors.csv')
def factors_export():return FileResponse(RESEARCH/'factor_metrics.csv',filename='short-term-factor-tests.csv')
