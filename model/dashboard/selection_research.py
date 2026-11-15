"""Local research-only comparison and hourly selection audit."""
from pathlib import Path
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
import csv
import io
import re
import sys
import threading
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

ROOT=Path(__file__).resolve().parents[1]/'short-term-research/selection-data-gate-v2'
CADENCE=ROOT.parent/'selection-12h-v3'
EVENT=ROOT.parent/'selection-event-v4'
sys.path.insert(0,str(EVENT))
import event_engine as e
router=APIRouter()
executor=ThreadPoolExecutor(max_workers=1)
lock=threading.Lock()
jobs={}


@router.get('/selection-research')
def page():return FileResponse(Path(__file__).with_name('selection-research.html'))


@router.get('/api/selection-research/meta')
def meta():
    return {'names':e.NAMES,
        **{k:e.base.read(EVENT/(k+'.json')) for k in ('protocol','assessment','validation','quarantine')},
        'metrics':e.base.read(EVENT/'all-metrics.json'),
        'cadence_assessment':e.base.read(CADENCE/'assessment.json'),
        'sources':e.base.read(ROOT/'sources.json'),
        'legacy-cost-metrics':e.base.read(ROOT/'metrics.json')}


class Period(BaseModel):
    start:date
    end:date
    fee:Literal[.0005,.001,.0015,.002,.003]=.0005
    delay:Literal[0,5]=0


def work(key,p):
    try:
        rows=[]
        for mode in e.NAMES:
            rows.append(e.summary(e.cached_run(str(p.start),str(p.end),mode,p.fee,p.delay)))
            with lock:jobs[key]['progress']=len(rows)
        with lock:jobs[key].update(status='complete',rows=rows)
    except Exception:
        import traceback
        traceback.print_exc()
        with lock:jobs[key].update(status='failed',error='计算失败，请查看研究日志；未改变模拟账户。')
    finally:
        e.prepare.cache_clear();e.cadence.prepare.cache_clear();e.parent.prepare.cache_clear()
        e.hourly_history.cache_clear();e.parent.hourly_history.cache_clear()


@router.post('/api/selection-research/jobs')
def create(p:Period,request:Request):
    if request.headers.get('origin') not in (None,'http://127.0.0.1:8765','http://localhost:8765'):
        raise HTTPException(403,'仅限本地请求')
    if not date(2025,1,1)<=p.start<=p.end<=date(2026,4,26):
        raise HTTPException(400,'本轮统一可比较范围为2025-01-01至2026-04-26')
    key=uuid.uuid4().hex
    with lock:
        if any(x['status']=='running' for x in jobs.values()):raise HTTPException(429,'已有研究任务正在计算')
        jobs[key]={'id':key,'status':'running','progress':0,'total':len(e.NAMES)}
    executor.submit(work,key,p)
    return {'id':key}


@router.get('/api/selection-research/jobs/{key}')
def job(key:str):
    with lock:
        if key not in jobs:raise HTTPException(404,'任务不存在')
        return dict(jobs[key])


def result(key):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{10,150}',key):raise HTTPException(400,'编号无效')
    p=(EVENT if '_event__' in key else CADENCE if '_12h__' in key else ROOT)/'results'/(key+'.json.gz')
    if not p.exists():raise HTTPException(404,'结果未计算')
    return e.base.read(p)


@router.get('/api/selection-research/results/{key}')
def detail(key:str):
    r=result(key)
    for k in ('orders','selection_trace','leverage_audit','funding_events'):r.pop(k,None)
    return r


@router.get('/api/selection-research/selection/{key}')
def selection(key:str,at:datetime):
    r=result(key)
    t=at.timestamp() if at.tzinfo else at.replace(tzinfo=__import__('datetime').timezone.utc).timestamp()
    candidates=[x for x in r['selection_trace'] if e.pd.Timestamp(x['date']).timestamp()<=t]
    return {'row':candidates[-1] if candidates else None,
            'note':'按当时可得信息排序，展示该时刻之前最近一次决策；名单可能因冷却、止损或数据中止而未全部成交。'}


@router.get('/api/selection-research/export/{key}')
def export(key:str):
    r=result(key);buf=io.StringIO()
    fields=['valid_for_comparison','symbol','layer','direction','entry_ts','exit_ts','qty','entry_price','exit_price','gross_pnl','pnl','fees','slippage','funding','reason']
    w=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore');w.writeheader()
    w.writerows({**t,'valid_for_comparison':r['valid_for_comparison']} for t in r['trades'])
    return Response('\ufeff'+buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{key}.csv"'})


@router.get('/api/selection-research/evidence/{name}')
def evidence(name:str):
    event_aliases={'event-protocol.json':'protocol.json','event-metrics.csv':'metrics.csv','event-validation.json':'validation.json','event-results.txt':'研究结果.txt','event-quarantine.json':'quarantine.json'}
    if name in event_aliases:return FileResponse(EVENT/event_aliases[name],filename=event_aliases[name])
    aliases={'12h-protocol.json':'protocol.json','12h-metrics.csv':'metrics.csv','12h-validation.json':'validation.json','12h-results.txt':'研究结果.txt'}
    if name in aliases:return FileResponse(CADENCE/aliases[name],filename=aliases[name])
    if name not in {'protocol.json','sources.json','metrics.csv','assessment.json','validation.json','quarantine.json','bootstrap.json','研究结果.txt','official-protocol.json','official-metrics.csv','official-assessment.json'}:
        raise HTTPException(404,'文件不存在')
    return FileResponse(ROOT/name,filename=name)


@router.get('/api/selection-research/original/{name}')
def original_evidence(name:str):
    if name not in {'protocol.json','metrics.csv','assessment.json','研究结果.txt'}:
        raise HTTPException(404,'文件不存在')
    return FileResponse(ROOT.parent/'selection-research-v1'/name,filename='original-'+name)
