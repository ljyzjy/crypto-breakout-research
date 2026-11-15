"""Causal, irreversible data-health quarantine; no return or later-validity inputs."""
import gc
from types import FunctionType, SimpleNamespace
import pandas as pd
import availability_engine as e
import selection_engine as original
import hourly_signals


def discover(manifest, cutoff=None):
    out={}
    for s,c in sorted(manifest['mapping'].items()):
        d=original.load_frame(c,'klines') if c else None
        if d is None:continue
        if cutoff is not None:d=d.loc[d.index+pd.Timedelta(minutes=5)<=cutoff]
        m=original.load_frame(c,'markPriceKlines')
        good=d.volume.gt(0)&d.close.gt(0)
        marked=m.close.reindex(d.index).gt(0) if m is not None else pd.Series(False,index=d.index)
        bad=d.index[good & ~marked]
        if len(bad):
            start=bad[0];observed=start+pd.Timedelta(minutes=5)
            out[s]=dict(symbol=s,contract=c,missing_bar_open=start.isoformat(),observed_at=observed.isoformat(),
                        observed_ts=int(observed.timestamp()),reason='closed_trade_bar_has_no_matching_mark')
    original.load_frame.cache_clear()
    return out


def filter_rows(rows,gates,hourly):
    result=[]
    for r in rows:
        t=pd.Timestamp(r['date']) if hourly else pd.Timestamp(r['date'],tz='UTC')
        blocked=[{**gates[p['symbol']]} for p in r['ranked']
                 if p['symbol'] in gates and gates[p['symbol']]['observed_ts']<=t.timestamp()]
        blocked_names={g['symbol'] for g in blocked}
        ranked=[p for p in r['ranked'] if p['symbol'] not in blocked_names]
        result.append({**r,'ranked':ranked,'daily_top2':[p['symbol'] for p in ranked[:2]],'excluded_data':blocked})
    return result


def main():
    gates=discover(original.manifest())
    e.base.dump(e.ROOT/'quarantine.json',gates)
    # Extend stored ranking audit from top5 to the entire at-most-20 eligible pool.
    # Score construction and all numeric parameters are exactly the frozen v1 code.
    import inspect
    source=inspect.getsource(hourly_signals.write_rankings).replace('.head(5)', '.head(20)')
    scope=dict(hourly_signals.write_rankings.__globals__)
    scope['e']=SimpleNamespace(base=e.base,ROOT=e.ROOT)
    exec(compile(source,'<full-ranking-audit>','exec'),scope)
    scope['write_rankings'](original.hourly_panel())
    original.hourly_panel.cache_clear()
    for selector in e.FACTOR_SELECTORS:
        path=e.ROOT/'signals'/f'{selector}-hourly.json.gz'
        rows=e.base.read(path)
        e.base.dump(path,filter_rows(rows,gates,True))
        del rows;gc.collect()
    weekly={k:filter_rows(rows,gates,False) for k,rows in original.rankings().items()}
    e.base.dump(e.ROOT/'weekly-rankings.json.gz',weekly)
    print('Causal quarantines',gates,flush=True)


if __name__=='__main__':main()
