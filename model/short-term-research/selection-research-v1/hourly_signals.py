"""Hourly ranking from completed bars and previous-day universe membership."""
import hashlib
import gc
import numpy as np
import pandas as pd
import selection_engine as e


def load_hourly():
    manifest = e.base.read(e.ROOT/'hourly-manifest.json')
    data = {}
    for s, entry in manifest['processed'].items():
        p = e.ROOT.parent/entry['path']
        assert hashlib.sha256(p.read_bytes()).hexdigest() == entry['sha256']
        d = pd.read_parquet(p)
        ix = pd.date_range(d.index.min(),d.index.max(),freq='h')
        d = d.reindex(ix)
        d['close'] = d.close.where(d.volume.gt(0))
        d['quote_volume'] = d.quote_volume.rolling(24).sum()
        d['volume'] = d.volume.rolling(24).sum()
        data[s] = d
    return data


def panel_from_hourly(data, daily_history, end='2026-04-26'):
    universe = {}
    for r in daily_history:
        if '2025-01-01' <= r['date'] <= end:
            for p in r['pool']:
                universe.setdefault(p['symbol'], {})[r['date']] = {
                    'median_volume':p['median_volume'], 'sigma':p['sigma'],
                    'eligible_count':r['eligible_count']}
    parts = []
    for hour in range(24):
        frames = []
        for s,d in data.items():
            z = d.loc[(d.index.hour+1)%24==hour,['close','volume','quote_volume']].copy()
            z['date'] = (z.index+pd.Timedelta(hours=1)).normalize()-pd.Timedelta(days=1)
            z['symbol'] = s
            frames.append(z.reset_index(drop=True))
        raw = pd.concat(frames,ignore_index=True)
        factors = e.factor_panel(raw)
        for s, allowed in universe.items():
            f = factors[s].copy()
            c = raw.loc[raw.symbol.eq(s)].set_index('date').close
            f['momentum'] = c/c.shift(30)-1
            f.index = f.index+pd.Timedelta(days=1,hours=hour)
            date_strings = f.index.strftime('%Y-%m-%d')
            keep = date_strings.isin(allowed)
            f = f.loc[keep].copy()
            f['symbol'] = s
            f['ts'] = f.index.as_unit('s').asi8
            for col in ('median_volume','sigma','eligible_count'):
                f[col] = [allowed[t.strftime('%Y-%m-%d')][col] for t in f.index]
            parts.append(f.reset_index(drop=True))
    return pd.concat(parts,ignore_index=True).sort_values(['ts','symbol'])


def write_rankings(panel, end='2026-04-26'):
    features = ['base_score','liquidity_score','continuity','residual_score']
    missing = panel[features+['momentum','selection_momentum']].isna().any(axis=1)
    if missing.any():
        records = panel.loc[missing,['ts','symbol']].to_dict('records')
        e.base.dump(e.ROOT/'hourly-input-gaps.json',records)
        raise ValueError(f'{len(records)} qualified hourly rows lack signal history; no silent coin deletion')
    pos = panel.loc[(panel.momentum>0)&(panel.selection_momentum>0)].copy()
    for k in features:
        pos[k+'_rank'] = pos.groupby('ts')[k].rank(method='average',pct=True)
    times = pd.date_range('2025-01-01',pd.Timestamp(end)+pd.Timedelta(hours=23),freq='h',tz='UTC')
    eligible = panel.groupby('ts').eligible_count.first().to_dict()
    specs = {'control':['base_score'],'residual':['residual_score'],
             'liquidity':['base_score_rank','liquidity_score_rank'],
             'continuity':['base_score_rank','continuity_rank'],
             'combined':[k+'_rank' for k in features]}
    for selector, cols in specs.items():
        z = pos.copy()
        z['score'] = z[cols].mean(axis=1)
        z = z.sort_values(['ts','score','symbol'],ascending=[True,False,True])
        counts = z.groupby('ts').size().to_dict()
        top = z.groupby('ts').head(5)
        groups = {int(ts):g.drop(columns=['ts']).to_dict('records') for ts,g in top.groupby('ts')}
        history = []
        for t in times:
            ts = int(t.timestamp())
            ranked = groups.get(ts,[])
            history.append({'date':t.isoformat(),'information_through':(t-pd.Timedelta(hours=1)).isoformat(),
                'universe_information_through':(t.normalize()-pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                'signal_available_at':ts,'eligible_count':int(eligible.get(ts,0)),
                'positive_candidates':int(counts.get(ts,0)), 'ranked':ranked,
                'daily_top2':[p['symbol'] for p in ranked[:2]],'selector':selector})
        e.base.dump(e.ROOT/'signals'/f'{selector}-hourly.json.gz',history)
        print('Hourly ranks written',selector,len(history),flush=True)
        del z,top,groups,history
        gc.collect()


def main():
    data = load_hourly()
    history = e.old.prior.slow_rankings()
    panel = panel_from_hourly(data,history)
    panel.to_parquet(e.ROOT/'hourly-factors.parquet',index=False)
    write_rankings(panel)
    print('Hourly factor panel',len(panel),'rows',flush=True)


if __name__=='__main__':
    main()
