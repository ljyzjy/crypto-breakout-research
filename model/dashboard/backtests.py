"""Bounded historical jobs, independent of the paper account and its database."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from importlib.metadata import version

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'user_data/dashboard_backtests'
router = APIRouter(prefix='/api/backtests')
jobs = {}
mutex = threading.Lock()


@lru_cache(maxsize=1)
def inputs():
    paths = [ROOT/'config.paper.json', ROOT/'config.public-data.json',
             ROOT/'user_data/strategies/DailyCandidates.py']
    bounds = []
    gaps = {}
    for coin in ('BTC', 'ETH'):
        p = ROOT/f'user_data/data/binance/{coin}_USDT-1h.feather'
        paths.append(p)
        dates = pd.read_feather(p, columns=['date']).date.sort_values()
        bounds.append((dates.min(), dates.max()))
        gaps[coin] = int(((dates.diff().dt.total_seconds().fillna(3600) / 3600)-1).clip(lower=0).sum())
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    digest = hashlib.sha256(json.dumps([hashes, version('freqtrade'),
             hashlib.sha256(Path(__file__).read_bytes()).hexdigest()], sort_keys=True).encode()).hexdigest()
    earliest = max(max(x[0] for x in bounds).date()+timedelta(days=75), date(2023,1,1))
    latest = min(x[1] for x in bounds)
    end = latest.date() if latest.hour == 23 else latest.date()-timedelta(days=1)
    return {'min_date':earliest.isoformat(), 'max_date':end.isoformat(),
            'strategy':'DailyMomentum', 'fee':0.001, 'initial':1000,
            'data_gaps_hours':gaps, 'fingerprint':digest, 'hashes':hashes,
            'engine':version('freqtrade')}


class Period(BaseModel):
    start: date
    end: date  # inclusive UTC calendar date


def validate_period(period):
    meta = inputs()
    if period.start > period.end:
        raise HTTPException(422, '开始日期不能晚于结束日期')
    if period.start.isoformat() < meta['min_date'] or period.end.isoformat() > meta['max_date']:
        raise HTTPException(422, f"可用日期为 {meta['min_date']} 至 {meta['max_date']}，已预留指标预热数据")
    return period


def job_key(period):
    return hashlib.sha256(f"{period.start}|{period.end}|{inputs()['fingerprint']}".encode()).hexdigest()[:24]


def old_archive(period):
    frozen = json.loads((ROOT/'comparison-v2/fingerprint.json').read_text())
    if any(frozen.get(k) != v for k,v in inputs()['hashes'].items()):
        return None
    rows = json.loads((ROOT/'comparison-v2/all_metrics.json').read_text())
    for row in rows:
        if (row['strategy']=='DailyMomentum' and row['fee']==.001
            and '-5m' not in row['scenario'] and '-neighbors' not in row['scenario']
            and row['start'][:10]==period.start.isoformat() and row['end'][:10]==period.end.isoformat()):
            return ROOT/'comparison-v2'/row['source_zip']
    return None


def extract(path, period, reused):
    with zipfile.ZipFile(path) as archive:
        stats = json.loads(archive.read(path.stem+'.json'))['strategy']['DailyMomentum']
        name = next(n for n in archive.namelist() if n.endswith('_DailyMomentum_wallet.feather'))
        wallet = pd.read_feather(io.BytesIO(archive.read(name)))
    if stats['backtest_start'][:10] != period.start.isoformat() or stats['backtest_end'][:10] != period.end.isoformat():
        raise ValueError('引擎实际回测区间与请求不一致，请检查数据覆盖和预热')
    equity = wallet.groupby('date').total_quote.sum().sort_index()
    equity.loc[pd.Timestamp(period.start, tz='UTC')] = 1000.0
    equity.loc[pd.Timestamp(stats['backtest_end'], tz='UTC')] = stats['final_balance']
    equity = equity.sort_index()
    dd = (equity / equity.cummax() - 1)*100
    # All statistics use hourly points; chart compression preserves extrema.
    raw = [[int(ts.timestamp()),float(eq),float(dd.loc[ts]),0] for ts,eq in equity.items()]
    stride = max(1, len(raw)//600)
    series = []
    for i in range(0,len(raw),stride):
        bucket = raw[i:i+stride]
        series.extend(sorted({tuple(bucket[0]),tuple(bucket[-1]),
            tuple(min(bucket,key=lambda r:r[1])),tuple(max(bucket,key=lambda r:r[1])),
            tuple(min(bucket,key=lambda r:r[2]))}))
    fields = ['pair','open_timestamp','close_timestamp','open_rate','close_rate','amount',
              'profit_abs','profit_ratio','exit_reason','trade_duration']
    trades = [{k:t.get(k) for k in fields} for t in stats['trades']]
    result = {'start':period.start.isoformat(),'end':period.end.isoformat(),
              'actual_start':stats['backtest_start'],'actual_end':stats['backtest_end'],
              'return_pct':stats['profit_total']*100,'profit':stats['profit_total_abs'],
              'final_equity':stats['final_balance'],'max_drawdown':float(-dd.min()),
              'trade_count':stats['total_trades'],'winrate':stats['winrate']*100,
              'profit_factor':stats['profit_factor'], 'series':series,
              'trades':sorted(trades,key=lambda t:t['open_timestamp'],reverse=True),
              'months':stats.get('periodic_breakdown',{}).get('month',[]),
              'reused_verified_archive':reused, 'created':time.time(),
              'source':str(path.relative_to(ROOT)), 'fingerprint':inputs()['fingerprint'],
              'engine':inputs()['engine'], 'hourly_points':len(raw)}
    return result


def run_job(key, period):
    folder = STORE/key
    folder.mkdir(parents=True,exist_ok=True)
    try:
        archive = old_archive(period)
        reused = archive is not None
        if archive is None:
            start = int(datetime.combine(period.start,datetime.min.time(),timezone.utc).timestamp())
            end = int(datetime.combine(period.end+timedelta(days=1),datetime.min.time(),timezone.utc).timestamp())-1
            cmd = [sys.executable,'-m','freqtrade','backtesting','--config','config.paper.json',
                   '--config','config.public-data.json','--userdir','user_data','--strategy','DailyMomentum',
                   '--timerange',f'{start}-{end}','--fee','0.001','--enable-protections',
                   '--cache','none','--export','trades','--breakdown','month','year',
                   '--backtest-directory',str(folder)]
            env = {k:v for k,v in os.environ.items() if not k.startswith('FREQTRADE__')}
            env['FREQTRADE__DRY_RUN']='true'
            (folder/'request.json').write_text(json.dumps({'start':str(period.start),'end':str(period.end),
              'fingerprint':inputs()['fingerprint'],'command':cmd},indent=2),encoding='utf-8')
            with open(folder/'run.log','w',encoding='utf-8') as log:
                completed = subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                                            timeout=360,creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode:
                raise ValueError('回测引擎运行失败，可能是行情元数据连接失败；可重试。日志保存在本次任务目录 run.log')
            archive = sorted(folder.glob('*.zip'))[-1]
        result = extract(archive,period,reused)
        temp = folder/'result.tmp'
        temp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        temp.replace(folder/'result.json')
        with mutex:
            jobs[key].update(status='complete',result=result,finished=time.time())
    except Exception as exc:
        message = str(exc) if isinstance(exc,ValueError) else '回测未完成，请检查任务日志后重试（未改动模拟账户）'
        if isinstance(exc,subprocess.TimeoutExpired):
            message='回测超过 6 分钟，已结束本次任务；请检查网络后重试'
        with mutex:
            jobs[key].update(status='failed',error=message,finished=time.time())


@router.get('/meta')
def metadata():
    return {k:v for k,v in inputs().items() if k!='hashes'}


@router.post('')
def submit(period:Period, request:Request):
    origin = request.headers.get('origin')
    if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'):
        raise HTTPException(403,'仅允许本机看板提交回测')
    validate_period(period)
    key = job_key(period)
    cached = STORE/key/'result.json'
    with mutex:
        if key in jobs and jobs[key]['status'] in ('running','complete'):
            return {'id':key,'status':jobs[key]['status']}
        if cached.exists():
            jobs[key]={'id':key,'status':'complete','result':json.loads(cached.read_text(encoding='utf-8'))}
            return {'id':key,'status':'complete'}
        if any(j['status']=='running' for j in jobs.values()):
            raise HTTPException(409,'已有一个回测正在运行，请等待完成后再提交')
        jobs[key]={'id':key,'status':'running','started':time.time(),'start':str(period.start),'end':str(period.end)}
    threading.Thread(target=run_job,args=(key,period),daemon=True).start()
    return {'id':key,'status':'running'}


@router.get('/{key}')
def status(key:str):
    with mutex:
        if key not in jobs:
            raise HTTPException(404,'任务不存在，请重新提交日期范围')
        return dict(jobs[key])
