"""Predeclared selection-factor experiments; never imports or changes a live account."""
from pathlib import Path
from functools import lru_cache
from types import FunctionType
import hashlib
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
V1 = ROOT.parent / 'selection-research-v1'
sys.path.insert(0, str(V1))
sys.path.insert(0, str(ROOT.parent / 'pool-dynamic-v1'))
import pool_dynamic_engine as previous

old = previous.old
base = previous.base
FACTOR_SELECTORS = {
    'control': '原较慢动量 · 对照',
    'liquidity': '动量 + 流动性代理',
    'continuity': '动量 + 趋势连续性',
    'residual': 'BTC 残差动量',
    'combined': '四因子等权 · 主要候选',
}
SELECTORS = {k+'_hourly':v+' · 每小时选币' for k,v in FACTOR_SELECTORS.items()}
SELECTORS.update({k+'_weekly':FACTOR_SELECTORS[k]+' · 每周选币' for k in ('control','combined')})
NAMES = {s + '__' + v: n + (' · 1×' if v == 'fixed1' else ' · 动态上限5×')
         for s, n in SELECTORS.items() for v in ('fixed1', 'tiered')}
SCENARIOS = [
    ('main', '2025-01-01', '2026-04-26', .001, 0),
    ('2025', '2025-01-01', '2025-12-31', .001, 0),
    ('2026', '2026-01-01', '2026-04-26', .001, 0),
    ('double', '2025-01-01', '2026-04-26', .002, 0),
    ('triple', '2025-01-01', '2026-04-26', .003, 0),
    ('delay', '2025-01-01', '2026-04-26', .001, 5),
]


def factor_panel(frame):
    """Every observation at t is calculated solely from closed days <= t."""
    ix = pd.date_range(pd.Timestamp('2024-09-01', tz='UTC'), frame.date.max(), tz='UTC')
    data = {s: d.set_index('date').reindex(ix) for s, d in frame.groupby('symbol')}
    btc = data['BTCUSDT']
    bc = btc.close.where(btc.volume.gt(0) & btc.quote_volume.gt(0))
    br = np.log(bc).diff()
    out = {}
    for symbol, d in data.items():
        c = d.close.where(d.volume.gt(0) & d.quote_volume.gt(0))
        logret = np.log(c).diff()
        ret = c / c.shift(1) - 1
        sigma = logret.rolling(20).std(ddof=1)
        beta = logret.rolling(60).cov(br) / br.rolling(60).var(ddof=1).replace(0, np.nan)
        variance = (logret.rolling(20).var(ddof=1) + beta**2 * br.rolling(20).var(ddof=1)
                    - 2 * beta * logret.rolling(20).cov(br)).clip(lower=0)
        residual_trend = np.log(c / c.shift(53)).shift(7) - beta * np.log(bc / bc.shift(53)).shift(7)
        residual_sigma = np.sqrt(variance)
        residual = residual_trend / residual_sigma.where(residual_sigma > 1e-10)
        residual = residual.mask(residual_sigma.le(1e-10) & residual_trend.notna(), 0.)
        continuity = logret.gt(0).astype(float).where(logret.notna()).rolling(30).mean()
        amihud = (ret.abs() / d.quote_volume.where(c.notna())).rolling(30).mean()
        slow = c.shift(7) / c.shift(60) - 1
        out[symbol] = pd.DataFrame({
            'base_score': slow / sigma, 'selection_momentum': slow,
            'liquidity_score': -amihud, 'amihud30': amihud,
            'continuity': continuity, 'beta60': beta,
            'residual_score': residual, 'residual_sigma20': residual_sigma,
        }, index=ix)
    return out


def rankings_from_frame(frame):
    factors = factor_panel(frame)
    ordinary = old.prior.old.rank_history(frame)[1]
    outputs = {s: [] for s in FACTOR_SELECTORS}
    required = {'control': ['base_score'], 'liquidity': ['base_score', 'liquidity_score'],
                'continuity': ['base_score', 'continuity'], 'residual': ['residual_score'],
                'combined': ['base_score', 'liquidity_score', 'continuity', 'residual_score']}
    for row in ordinary:
        t = pd.Timestamp(row['information_through'], tz='UTC')
        pool = []
        for p in row['pool']:
            f = factors[p['symbol']].loc[t]
            pool.append({**p, **{k: float(v) for k, v in f.items()}})
        positive = [p for p in pool if p['momentum'] > 0 and p['selection_momentum'] > 0]
        for selector in FACTOR_SELECTORS:
            candidates = [dict(p) for p in positive if all(np.isfinite(p[k]) for k in required[selector])]
            if candidates:
                table = pd.DataFrame(candidates).set_index('symbol')
                columns = required[selector]
                pct = table[columns].rank(method='average', pct=True)
                for p in candidates:
                    p['score'] = float(p['base_score'] if selector == 'control' else
                                       p['residual_score'] if selector == 'residual' else
                                       pct.loc[p['symbol']].mean())
                    p['component_percentiles'] = {k: float(pct.loc[p['symbol'], k]) for k in columns}
            ranked = sorted(candidates, key=lambda p: (-p['score'], p['symbol']))
            outputs[selector].append({**row, 'pool': pool, 'ranked': ranked,
                                      'daily_top2': [p['symbol'] for p in ranked[:2]],
                                      'selector': selector})
    return outputs


@lru_cache(maxsize=1)
def rankings():
    # Keep the original full daily snapshot immutable; all formulas are backward-looking.
    return base.read(ROOT / 'weekly-rankings.json.gz')


@lru_cache(maxsize=1)
def manifest():
    return base.read(ROOT / 'data-manifest.json')


@lru_cache(maxsize=3)
def load_frame(symbol, kind):
    entry = manifest()['processed'].get(symbol + '/' + kind)
    if not entry:
        return None
    path = ROOT.parent / entry['path']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], path
    return pd.read_parquet(path)


@lru_cache(maxsize=1)
def leverage_features():
    syms = tuple(manifest()['mapping'])
    fd = {}
    for s in syms:
        c = manifest()['mapping'][s]
        f = load_frame(c, 'fundingRate') if c else None
        fd[s] = f if f is not None else pd.DataFrame(
            {'last_funding_rate': pd.Series(dtype=float)}, index=pd.DatetimeIndex([], tz='UTC'))
    scope = dict(previous.seed.features_from_daily.__globals__)
    scope['SYMBOLS'] = syms
    fn = FunctionType(previous.seed.features_from_daily.__code__, scope)
    result = fn(old.prior.old.daily(), fd)
    load_frame.cache_clear()
    return result


@lru_cache(maxsize=1)
def hourly_history(selector):
    return base.read(ROOT/'signals'/f'{selector}-hourly.json.gz')


@lru_cache(maxsize=1)
def hourly_panel():
    return pd.read_parquet(V1/'hourly-factors.parquet')


@lru_cache(maxsize=1)
def prepare(start, end, selector, delay=0):
    factor, cadence = selector.rsplit('_',1)
    lo = pd.Timestamp(start,tz='UTC'); hi = pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)
    source = hourly_history(factor) if cadence=='hourly' else rankings()[factor]
    history = [r for r in source if lo <= pd.Timestamp(r['date']) < hi] if cadence=='hourly' else [r for r in source if start<=r['date']<=end]
    selected = set()
    for i, row in enumerate(history):
        if cadence=='hourly' or i == 0 or pd.Timestamp(row['date']).weekday() == 0:
            selected.update(row['daily_top2'])
    symbols = tuple(sorted(selected | {'BTCUSDT', 'ETHUSDT'}))
    trace = {int(pd.Timestamp(r['date']).timestamp() if cadence=='hourly' else pd.Timestamp(r['date'],tz='UTC').timestamp()):r for r in history}
    ix = pd.date_range(pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC') + pd.Timedelta(days=1), freq='5min', inclusive='left')
    info = ix - pd.Timedelta(minutes=delay)
    days = info.normalize() - pd.Timedelta(days=1)
    preceding = ix - pd.Timedelta(minutes=5)
    months = ix.strftime('%Y-%m')
    px, mk, mom, budgets, rates, ok, avail = {}, {}, {}, {}, {}, {}, {}
    daily_factors = old.prior.old.rankings()[0]
    for s in symbols:
        c = manifest()['mapping'].get(s)
        d = load_frame(c, 'klines') if c else None
        m = load_frame(c, 'markPriceKlines') if c else None
        px[s] = d.reindex(ix)[['open', 'high', 'low', 'close', 'volume']].to_numpy(float) if d is not None else np.full((len(ix), 5), np.nan)
        mk[s] = m.reindex(ix)[['open', 'high', 'low', 'close']].to_numpy(float) if m is not None else np.full((len(ix), 4), np.nan)
        pre = d.reindex(preceding) if d is not None else None
        prem = m.reindex(preceding) if m is not None else None
        executable = (pre.volume.gt(0) & pre.close.gt(0)).to_numpy() if pre is not None else np.zeros(len(ix), bool)
        marked = prem.close.gt(0).to_numpy() if prem is not None else np.zeros(len(ix), bool)
        avail[s] = np.where(executable, np.where(marked, 1, 2), 0)
        fd = load_frame(c, 'fundingRate') if c else None
        rates[s] = fd.last_funding_rate.reindex(ix).fillna(0).to_numpy(float) if fd is not None else np.zeros(len(ix))
        valid = np.zeros(len(ix), bool)
        if fd is not None:
            for when, r in fd.iterrows():
                lo = ix.searchsorted(when - pd.Timedelta(hours=float(r.funding_interval_hours)))
                hi = ix.searchsorted(when, side='right')
                valid[lo:hi] = True
            if len(fd):
                valid[ix.searchsorted(fd.index[-1]):ix.searchsorted(fd.index[-1] + pd.Timedelta(hours=float(fd.funding_interval_hours.iloc[-1])))] = True
            valid &= months.isin(manifest()['availability'].get(s, {}).get('fundingRate', []))
        ok[s] = valid
        q = daily_factors[s].reindex(days)
        v = q['valid'].fillna(False).to_numpy(bool) & np.isfinite(q.mom.to_numpy(float))
        if cadence=='hourly':
            hf = hourly_panel().loc[hourly_panel().symbol.eq(s)].set_index('ts')
            hr = hf.momentum.reindex(info.floor('h').as_unit('s').asi8).to_numpy(float)
            mom[s] = np.where(np.isfinite(hr)&(hr>0),1,0).astype(np.int8)
        else:
            mom[s] = np.where(v & q.mom.gt(0).to_numpy(), 1, 0).astype(np.int8)
        sigma = q.sigma.to_numpy(float)
        budgets[s] = np.where(v & np.isfinite(sigma) & (sigma > 0), np.minimum(200, 2 / np.maximum(sigma, 1e-9)), 0)
    load_frame.cache_clear()
    return dict(symbols=symbols, index=ix, px=px, mk=mk, rates=rates, ok=ok, avail=avail,
                mom=mom, budgets=budgets, trace=trace,
                decision=np.array((info.minute == 0) & (info.second == 0) & (info >= pd.Timestamp(start, tz='UTC'))))


def simulate(start, end, mode, fee=.001, delay=0, fixture=None, feature_fixture=None):
    selector, variant = mode.split('__')
    assert mode in NAMES
    z = fixture if fixture is not None else prepare(start, end, selector, delay)
    f = feature_fixture if feature_fixture is not None else leverage_features()
    scope = dict(previous.simulate.__globals__)
    scope['NAMES'] = NAMES
    # The original simulator branches for rank_buffer/delayed_retry only; these new
    # selectors all follow unchanged base execution. No global monkey-patching.
    from selection_execution import simulate_path
    scope['hourly_rotation'] = selector.endswith('_hourly')
    fn = FunctionType(simulate_path.__code__, scope, argdefs=simulate_path.__defaults__)
    result = fn(start, end, mode, fee, delay, z, f)
    result['research_version'] = 'selection-data-gate-v2'
    result['history_seen'] = True
    return result


def key(start, end, mode, fee, delay):
    return f'{start}_{end}_{mode}_f{round(fee*10000)}_d{delay}'


def cached_run(start, end, mode, fee=.001, delay=0):
    ident = key(start, end, mode, fee, delay)
    p = ROOT / 'results' / (ident + '.json.gz')
    if p.exists():
        return base.read(p)
    result = simulate(start, end, mode, fee, delay)
    result['id'] = ident
    base.dump(p, result)
    return result


def summary(result):
    return previous.summary(result)
