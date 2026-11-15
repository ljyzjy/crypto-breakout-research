"""Read-only evidence for the unreleased selection candidate."""
import json
from pathlib import Path
from datetime import date
from functools import lru_cache
from fastapi import APIRouter,HTTPException

ROOT=Path(__file__).resolve().parents[1]/'selection-v1'
router=APIRouter(prefix='/api/selection')

def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))

@lru_cache(maxsize=2)
def history(late):
    span='2025-01-01-2026-10-31' if late else '2023-01-01-2024-12-31'
    return read(f'results/selection-{span}-0.001.json')

@router.get('/audit')
def audit(day:date=date(2026,10,31)):
    if not date(2023,1,1)<=day<=date(2026,10,31):raise HTTPException(422,'审计日期为 2023-01-01 至 2026-10-31')
    run=history(day.year>=2025)
    row=next(t for t in run['trace'] if t['date']==day.isoformat())
    return {'status':'research_rejected_for_promotion','decision':row,'start':run['start'],
            'rules':read('rules.json'),'formation':read('universe.json'),
            'summary':read('summary.json'),'validation':read('causality-validation.json')}
