"""Read-only single-strategy results. Date changes slice the continuous run, no other backtests."""
from pathlib import Path
from datetime import date,datetime,timezone,timedelta
from functools import lru_cache
import json
import numpy as np
import pandas as pd
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse,Response

ROOT=Path(__file__).resolve().parents[1]/'short-term-research/minute-intraday-v1'
router=APIRouter()
SCENARIOS={'main':'基础成本','fee2':'手续费2倍','fee3':'手续费3倍','slip2':'滑点2倍','delay1':'额外延迟1分钟'}
def read(name,default=None):
    p=ROOT/name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
def records(d):return json.loads(d.to_json(orient='records'))

@router.get('/minute-research')
def page():return FileResponse(Path(__file__).with_name('minute-research.html'))

@router.get('/api/minute-research/meta')
def meta():
    return {'protocol':read('protocol.json'),'metrics':read('metrics.json',[]),
       'assessment':read('assessment.json',{}),'validation':read('validation.json',{}),
       'features':read('feature-manifest.json',{}),'quarantine':read('quarantine.json',{}),
       'seconds':read('seconds/status.json',{}),'progress':read('progress.json',{}),'scenarios':SCENARIOS}

@lru_cache(maxsize=2)
def load(scenario):
    if scenario not in SCENARIOS:raise HTTPException(400,'未知场景')
    p=ROOT/'results'/(scenario+'-curve.parquet')
    if not p.exists():raise HTTPException(409,'该场景还未完成')
    return pd.read_parquet(p),pd.DataFrame(read('results/'+scenario+'-trades.json',[]))

def period(scenario,start,end):
    spec=read('protocol.json');start=start or date.fromisoformat(spec['start']);end=end or date.fromisoformat(spec['end'])
    if start>end or str(start)<spec['start'] or str(end)>spec['end']:raise HTTPException(400,'日期超出已验证历史区间')
    lo=int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)
    hi=int(datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)
    c,t=load(scenario);before=c[c.ts<=lo];initial=float(before.equity.iloc[-1]) if len(before) else 1000.
    selected=c[c.ts.gt(lo)&c.ts.le(hi)].copy()
    if selected.empty:raise HTTPException(400,'该区间没有可用结果')
    trades=t[t.exit_ts.gt(lo)&t.exit_ts.le(hi)].copy() if len(t) else t.copy()
    return selected,trades,initial,lo,hi

@router.get('/api/minute-research/result')
def result(scenario:str='main',start:date|None=None,end:date|None=None):
    c,t,initial,lo,hi=period(scenario,start,end)
    peak=np.maximum.accumulate(np.r_[initial,c.equity.to_numpy()])[1:]
    c['window_drawdown']=100*(1-c.equity.to_numpy()/peak)
    last=float(c.equity.iloc[-1]);days=(min(hi,int(c.ts.iloc[-1]))-lo)/86400000
    full=read('results/'+scenario+'-summary.json',{})
    summary={'initial':initial,'final':last,'net':last-initial,'return_pct':100*(last/initial-1),
       'annualized_return_pct':100*((last/initial)**(365/days)-1) if days>=365 and last>0 else None,
       'max_drawdown':float(c.window_drawdown.max()),'closed_trades':len(t),
       'mean_holding_minutes':float(t.holding_minutes.mean()) if len(t) else 0.,
       'win_rate':float(100*t.net.gt(0).mean()) if len(t) else 0.,'days':days,
       'valid_for_comparison':full.get('valid_for_comparison',False),
       'permanent_pause_ts':full.get('permanent_pause_ts'),'full_period_intrabar_stress_dd':full.get('intrabar_stress_dd'),
       'mean_exposure_pct':float(c.exposure.mean())}
    # Last equity plus worst drawdown in each bin; KPI still uses every minute.
    step=max(1,int(np.ceil(len(c)/1200)));c['bin']=np.arange(len(c))//step
    plot=c.groupby('bin').agg(ts=('ts','last'),equity=('equity','last'),drawdown=('window_drawdown','max'))
    byside=[];byexit=[];bycoin=[]
    if len(t):
        for column,out in [('side',byside),('reason',byexit),('symbol',bycoin)]:
            for k,g in t.groupby(column):out.append({'name':str(k),'trades':len(g),'net':float(g.net.sum())})
    cost={k:float(t[k].sum()) if len(t) else 0. for k in ['gross','fees','slippage','funding','net']}
    return {'summary':summary,'curve':records(plot),'trades':records(t.sort_values('exit_ts',ascending=False).head(100)) if len(t) else [],
       'costs_closed_trades':cost,'by_side':byside,'by_exit':byexit,'by_coin':sorted(bycoin,key=lambda x:x['net'],reverse=True),
       'note':'日期筛选是连续账户权益切片，未重新开仓或重置风控。交易/成本按本区间平仓记录统计；跨边界持仓会使其与区间权益差异不完全相等。'}

@router.get('/api/minute-research/ranks')
def ranks(at:datetime):
    if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
    ts=int(at.timestamp()*1000);p=ROOT/'hourly-ranks.parquet'
    if not p.exists():raise HTTPException(409,'排名尚未构建')
    d=pd.read_parquet(p);eligible=d[d.hour<=ts]
    if eligible.empty:return {'hour':None,'rows':[]}
    hour=int(eligible.hour.max())
    if ts-hour>=3600000:return {'hour':None,'rows':[],'note':'该小时没有有效候选，不沿用更早排名'}
    q=read('quarantine.json',{})
    out=d[d.hour.eq(hour)].copy();out=out[[ts<q.get(s,{}).get('known_ts',10**18) for s in out.symbol]]
    return {'hour':hour,'rows':records(out.sort_values(['side','rank'],ascending=[False,True]))}

@router.get('/api/minute-research/export')
def export(scenario:str='main',start:date|None=None,end:date|None=None):
    _,t,*_=period(scenario,start,end)
    blob=t.to_csv(index=False).encode('utf-8-sig')
    return Response(blob,media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="minute-{scenario}-trades.csv"'})

@router.get('/api/minute-research/evidence/{name}')
def evidence(name:str):
    if name not in {'protocol.json','frozen.json','validation.json','metrics.csv','研究结果.txt'}:raise HTTPException(404)
    p=ROOT/name
    if not p.exists():raise HTTPException(404)
    return FileResponse(p,filename=name)
