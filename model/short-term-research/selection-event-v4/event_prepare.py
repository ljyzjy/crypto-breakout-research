def prepare_path(start, end, selector, delay=0):
    factor, cadence = selector.rsplit('_',1)
    lo = pd.Timestamp(start,tz='UTC'); hi = pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)
    source = hourly_history(factor) if cadence=='hourly' else rankings()[factor]
    history = [r for r in source if lo <= pd.Timestamp(r['date']) < hi] if cadence=='hourly' else [r for r in source if start<=r['date']<=end]
    selected = set()
    for i, row in enumerate(history):
        if cadence=='hourly' or i == 0 or pd.Timestamp(row['date']).weekday() == 0:
            selected.update(p['symbol'] for p in row['ranked'])
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
