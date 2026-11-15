"""Local, read-only paper-trading dashboard. No exchange credentials required."""
import atexit
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backtests import router as backtest_router
from selection_audit import router as selection_router
from strategy_catalog import catalog
from short_term import router as short_term_router
from research_public import router as research_public_router
from coin_lab import router as coin_lab_router
from rotation_lab import router as rotation_lab_router
from short_factor import router as short_factor_router
from dynamic_leverage import router as dynamic_leverage_router
from pool_dynamic import router as pool_dynamic_router
from selection_research import router as selection_research_router
from minute_research import router as minute_research_router

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'user_data'
CONFIG = ROOT / 'config.dashboard.local.json'
DB = DATA / 'dashboard-momentum.sqlite'
BASE = 'http://127.0.0.1:8080/api/v1/'
INITIAL = 1000.0
lock = threading.Lock()
state = {'ok': False, 'error': '模拟引擎正在启动并加载行情', 'updated': None}
halt = threading.Event()


def make_config():
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
        auth = cfg['api_server']
    else:
        auth = {'username': 'paper-local', 'password': secrets.token_urlsafe(32),
                'jwt_secret_key': secrets.token_urlsafe(48), 'ws_token': secrets.token_urlsafe(32)}
    auth.update(enabled=True, listen_ip_address='127.0.0.1', listen_port=8080,
                verbosity='error', enable_openapi=False, CORS_origins=[])
    cfg = {'dry_run': True, 'dry_run_wallet': INITIAL, 'strategy': 'DailyMomentum',
           'trading_mode': 'spot', 'stake_amount': 100, 'max_open_trades': 2,
           'fee': 0.001, 'force_entry_enable': False, 'initial_state': 'running',
           'bot_name': 'momentum-30-paper', 'exchange': {'key': '', 'secret': ''},
           'api_server': auth}
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    return auth


def api_session():
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))['api_server']
    session = requests.Session()
    session.trust_env = False
    session.auth = (cfg['username'], cfg['password'])
    return session


def init_db():
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS equity (ts REAL PRIMARY KEY, equity REAL NOT NULL)')


def record_equity(ts, equity):
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError('invalid equity')
    with sqlite3.connect(DB) as db:
        last = db.execute('SELECT MAX(ts) FROM equity').fetchone()[0]
        if last is None or ts - last >= 60:
            db.execute('INSERT INTO equity VALUES (?, ?)', (ts, equity))


def equity_series():
    with sqlite3.connect(DB) as db:
        return db.execute('SELECT ts, equity FROM equity ORDER BY ts').fetchall()


def drawdowns(rows):
    peak = INITIAL
    result = []
    segment, previous = 0, None
    for ts, eq in rows:
        if previous is not None and ts - previous > 180:
            segment += 1
        peak = max(peak, eq)
        result.append([ts, eq, (eq / peak - 1) * 100, segment])
        previous = ts
    return result


def poll():
    session = api_session()
    def get(path):
        response = session.get(BASE + path, timeout=12)
        response.raise_for_status()
        return response.json()
    while not halt.is_set():
        try:
            cfg = get('show_config')
            if cfg['dry_run'] is not True or cfg['strategy'] != 'DailyMomentum':
                raise ValueError('模拟模式或策略不匹配')
            health = get('health')
            positions = get('status')
            profit = get('profit')
            signals = []
            for pair in ('BTC/USDT', 'ETH/USDT'):
                candles = get('pair_candles?pair=' + pair + '&timeframe=1h&limit=1')
                if not candles['data'] or time.time() - candles['data_stop_ts']/1000 > 7800:
                    raise ValueError('行情 K 线尚未就绪或已过期，暂停净值采样')
                row = dict(zip(candles['columns'], candles['data'][-1]))
                momentum = row.get('daily_momentum')
                if momentum is None or not math.isfinite(momentum):
                    raise ValueError('30 日动量预热尚未完成')
                signals.append({'pair':pair, 'momentum':momentum,
                                'candle_ts':candles['data_stop_ts'], 'close':row['close']})
            # Pagination keeps the complete realized history available after months of use.
            trades, offset = [], 0
            while True:
                batch = get(f'trades?limit=500&offset={offset}')
                trades.extend(batch['trades'])
                offset += len(batch['trades'])
                if offset >= batch['total_trades'] or not batch['trades']:
                    break
            now = time.time()
            heartbeat = health.get('last_process_ts')
            if not heartbeat or now - heartbeat > 180:
                raise ValueError('引擎尚未完成行情处理，或心跳已过期')
            if cfg['state'].lower() != 'running':
                raise ValueError('模拟引擎已停止交易循环')
            pnl = float(profit['profit_all_coin'])
            if not math.isfinite(pnl):
                raise ValueError('持仓估值暂不可用')
            equity = INITIAL + pnl
            record_equity(now, equity)
            payload = dict(ok=True, updated=now, error=None, equity=equity,
                           pnl=pnl, realized=profit['profit_closed_coin'],
                           unrealized=pnl-profit['profit_closed_coin'],
                           positions=positions, trades=trades,
                           signals=signals,
                           closed_count=profit['closed_trade_count'],
                           health=health, strategy=cfg['strategy'], dry_run=True)
            with lock:
                state.update(payload)
        except Exception as exc:
            # Do not expose URL/auth details, logs, config or stack traces to the browser.
            message = str(exc) if isinstance(exc, ValueError) else '暂时无法读取模拟引擎；保留最后一次数据，正在重连'
            with lock:
                state.update(ok=False, error=message)
        halt.wait(15)


@asynccontextmanager
async def lifespan(app):
    init_db()
    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    yield
    halt.set()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])
app.include_router(backtest_router)
app.include_router(selection_router)
app.include_router(short_term_router)
app.include_router(research_public_router)
app.include_router(coin_lab_router)
app.include_router(rotation_lab_router)
app.include_router(short_factor_router)
app.include_router(dynamic_leverage_router)
app.include_router(pool_dynamic_router)
app.include_router(selection_research_router)
app.include_router(minute_research_router)


@app.get('/')
def index():
    return FileResponse(Path(__file__).with_name('index.html'))


@app.get('/backtest')
def historical_page():
    return FileResponse(Path(__file__).with_name('backtest.html'))


@app.get('/dashboard.css')
def stylesheet():
    return FileResponse(Path(__file__).with_name('dashboard.css'), media_type='text/css')


@app.get('/selection')
def selection_page():
    return FileResponse(Path(__file__).with_name('selection.html'))


@app.get('/api/state')
def snapshot():
    with lock:
        result = dict(state)
    rows = equity_series()
    if result.get('updated') and (not rows or result['updated'] > rows[-1][0]):
        rows.append((result['updated'], result['equity']))
    series = drawdowns(rows)
    result['max_drawdown'] = -min([r[2] for r in series], default=0)
    result['current_drawdown'] = -series[-1][2] if series else None
    result['capture_start'] = series[0][0] if series else None
    # Preserve chart extrema as well as evenly spaced points; statistics use every sample.
    if len(series) > 1500:
        stride = math.ceil(len(series) / 500)
        compact = []
        for start in range(0, len(series), stride):
            bucket = series[start:start+stride]
            compact.extend(sorted({tuple(bucket[0]), tuple(bucket[-1]),
                                   tuple(min(bucket, key=lambda r:r[1])),
                                   tuple(max(bucket, key=lambda r:r[1])),
                                   tuple(min(bucket, key=lambda r:r[2]))}))
        series = compact
    result['series'] = series
    result['app'] = 'momentum-paper-dashboard'
    if result.get('updated') and time.time() - result['updated'] > 90:
        result.update(ok=False, error='账户数据已过期，等待模拟引擎恢复')
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


@app.get('/strategies')
def strategies_page():
    return FileResponse(Path(__file__).with_name('strategies.html'))


@app.get('/api/strategies')
def strategies_catalog():
    return JSONResponse(catalog(), headers={'Cache-Control': 'no-store'})


@app.get('/api/equity.csv')
def export():
    lines = ['timestamp_utc,equity_usdt,drawdown_pct']
    from datetime import datetime, timezone
    for ts, eq, dd, segment in drawdowns(equity_series()):
        lines.append(f'{datetime.fromtimestamp(ts, timezone.utc).isoformat()},{eq:.8f},{dd:.8f}')
    return Response('\n'.join(lines), media_type='text/csv',
                    headers={'Content-Disposition':'attachment; filename="paper-equity.csv"'})


def launch(dashboard_only=False):
    DATA.mkdir(exist_ok=True)
    # An OS lock prevents two dashboard instances from sharing the trading database.
    import msvcrt
    guard = open(DATA / 'dashboard.lock', 'a+b')
    guard.seek(0); guard.write(b'1'); guard.flush(); guard.seek(0)
    msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
    if dashboard_only:
        # Refresh the read-only UI without restarting or reconfiguring the paper engine.
        import psutil
        process_file = DATA / 'dashboard-processes.local.json'
        info = json.loads(process_file.read_text(encoding='utf-8'))
        engine = info['engine']
        process = psutil.Process(engine['pid'])
        if abs(process.create_time() - engine['created']) >= 0.01:
            raise RuntimeError('Saved engine identity does not match; refusing to attach.')
        args = process.cmdline()
        if 'freqtrade' not in args or 'DailyMomentum' not in args:
            raise RuntimeError('Saved process is not the expected paper engine.')
        response = api_session().get(BASE + 'show_config', timeout=10)
        response.raise_for_status()
        cfg = response.json()
        if cfg.get('dry_run') is not True or cfg.get('strategy') != 'DailyMomentum':
            raise RuntimeError('API is not the expected paper account; refusing to attach.')
        info['dashboard'] = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
        process_file.write_text(json.dumps(info), encoding='utf-8')
        uvicorn.run(app, host='127.0.0.1', port=8765, log_level='warning')
        return
    make_config()
    env = {k:v for k,v in os.environ.items() if not k.startswith('FREQTRADE__')}
    env['FREQTRADE__DRY_RUN'] = 'true'
    logs = DATA / 'logs'; logs.mkdir(exist_ok=True)
    log = open(logs / 'momentum-engine-console.log', 'a', encoding='utf-8')
    command = [sys.executable, '-m', 'freqtrade', 'trade', '--config', 'config.paper.json',
               '--config', 'config.public-data.json', '--config', CONFIG.name,
               '--userdir', 'user_data', '--strategy', 'DailyMomentum',
               '--db-url', 'sqlite:///user_data/paper-DailyMomentum.sqlite',
               '--logfile', 'user_data/logs/paper-DailyMomentum.log']
    child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    import psutil
    info = {'dashboard': {'pid':os.getpid(), 'created':psutil.Process().create_time()},
            'engine': {'pid':child.pid, 'created':psutil.Process(child.pid).create_time()}}
    (DATA / 'dashboard-processes.local.json').write_text(json.dumps(info), encoding='utf-8')
    atexit.register(lambda: child.terminate() if child.poll() is None else None)
    uvicorn.run(app, host='127.0.0.1', port=8765, log_level='warning')


def stop():
    import psutil
    path = DATA / 'dashboard-processes.local.json'
    if not path.exists():
        print('No saved paper process.'); return
    # User-invoked local shutdown; this is never exposed through the browser.
    try:
        api_session().post(BASE+'stop', timeout=5)
    except requests.RequestException:
        pass
    info = json.loads(path.read_text())
    for name in ('engine', 'dashboard'):
        item = info[name]
        try:
            process = psutil.Process(item['pid'])
            if abs(process.create_time()-item['created']) < 0.01:
                process.terminate()
                process.wait(timeout=10)
        except psutil.NoSuchProcess:
            pass
    print('Paper services stopped. Trade history and equity retained.')


if __name__ == '__main__':
    stop() if '--stop' in sys.argv else launch(dashboard_only='--dashboard-only' in sys.argv)
