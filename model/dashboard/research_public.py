"""Read-only public research and prospective paper status; no exchange actions."""
import json,csv,io
from pathlib import Path
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse,Response
from performance_metrics import enrich,enrich_many
router=APIRouter()
ROOT=Path(__file__).resolve().parents[1]/'short-term-research'

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

@router.get('/research')
def page():return FileResponse(Path(__file__).with_name('research.html'))

@router.get('/api/research/meta')
def meta():
 return {'spot':enrich_many(read(ROOT/'public-research-v1/metrics.json')),'decisions':read(ROOT/'public-research-v1/decision.json'),
         'perpetual':enrich_many(read(ROOT/'leverage-v1/metrics.json')),'perpetual_protocol':read(ROOT/'leverage-v1/protocol.json'),
         'sources':read(ROOT/'public-research-v1/sources.json'),'repositories':read(ROOT/'public-research-v1/repositories.json'),
         'verification':read(ROOT/'leverage-v1/verification.json'),'risk_comparison':read(ROOT/'public-research-v1/risk-comparison.json'),
         'risk_budget':{'metrics':enrich_many(read(ROOT/'risk-budget-v1/metrics.json')),'decisions':read(ROOT/'risk-budget-v1/decision.json'),'verification':read(ROOT/'risk-budget-v1/verification.json')}}

@router.get('/api/research/forward')
def forward():
 path=ROOT/'public-research-v1/forward/state.json'
 if not path.exists():return {'status':'not_started','portfolios':{}}
 d=read(path);d.pop('source_hashes',None);d.pop('process',None)
 return d

@router.get('/api/research/perpetual/{key}')
def detail(key:str):
 rows=enrich_many(read(ROOT/'leverage-v1/metrics.json'))
 if key not in {r['id'] for r in rows}:raise HTTPException(404,'未找到固定研究场景')
 import gzip
 with gzip.open(ROOT/'leverage-v1/results'/(key+'.json.gz'),'rt',encoding='utf-8') as f:d=json.load(f)
 d.pop('orders',None);return enrich(d)

@router.get('/api/research/export/perpetual.csv')
def export():
 rows=enrich_many(read(ROOT/'leverage-v1/metrics.json'));buf=io.StringIO()
 writer=csv.DictWriter(buf,fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
 writer.writeheader();writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)
 return Response('\ufeff'+buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="perpetual-120-scenarios.csv"'})
