"""Acquire the same replacement execution union for all amended strategies."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import pandas as pd
import availability_engine as e
import selection_engine as original
import importlib.util
spec=importlib.util.spec_from_file_location('selection_acquisition',original.ROOT/'acquire_data.py')
a=importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def main():
    a.ROOT=e.ROOT
    # Reuse the existing plan generator, with only the amended histories/output root.
    from types import FunctionType
    scope=dict(a.make_plan.__globals__);scope['e']=e;scope['ROOT']=e.ROOT
    symbols,plan=FunctionType(a.make_plan.__code__,scope)()
    manifest=deepcopy(original.manifest())
    keys={r['key'] for r in e.old.manifest()['archives']}
    keys.update(r['key'] for r in manifest['supplemental_archives'])
    contracts={x.split('/')[-2] for x in a.cached_listing('data/futures/um/monthly/klines/','/')}
    jobs=[]
    for s in sorted(symbols):
        manifest['mapping'].setdefault(s,next((c for c in (s,'1000'+s,'1000000'+s) if c in contracts),None))
        c=manifest['mapping'][s]
        if not c:continue
        months={m for coin,m in plan if coin==s}
        manifest['availability'].setdefault(s,{})
        for kind in ('klines','markPriceKlines','fundingRate'):
            prefix=f'data/futures/um/monthly/{kind}/{c}/'+('' if kind=='fundingRate' else '5m/')
            archives=[k for k in a.cached_listing(prefix) if k.endswith('.zip')]
            manifest['availability'][s][kind]=sorted(k[-11:-4] for k in archives)
            jobs.extend(k for k in archives if k[-11:-4] in months and k not in keys)
    jobs=sorted(set(jobs));e.base.dump(e.ROOT/'archive-plan.json',jobs)
    print('Replacement archive count',len(jobs),flush=True)
    records=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(a.archive,k) for k in jobs]):records.append(f.result())
    grouped={}
    for r in records:
        bits=r['key'].split('/');grouped.setdefault((bits[5],bits[4]),[]).append(r)
    for (c,kind),items in grouped.items():
        entry=manifest['processed'].get(c+'/'+kind)
        prior=pd.read_parquet(e.ROOT.parent/entry['path']) if entry else None
        new=pd.concat([a.parse(r,kind) for r in items]).sort_index()
        if prior is not None:
            overlap=prior.index.intersection(new.index)
            if len(overlap):pd.testing.assert_frame_equal(prior.loc[overlap],new.loc[overlap],check_dtype=False,check_freq=False)
            new=pd.concat([prior,new.loc[~new.index.isin(prior.index)]]).sort_index()
        assert not new.index.duplicated().any()
        path=e.ROOT/'data'/f'{c}-{kind}.parquet';path.parent.mkdir(exist_ok=True)
        new.to_parquet(path)
        manifest['processed'][c+'/'+kind]=dict(path=str(path.relative_to(e.ROOT.parent)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),rows=len(new))
    manifest['revision_archives']=records
    e.base.dump(e.ROOT/'data-manifest.json',manifest)
    print('Shared manifest written',len(manifest['processed']),flush=True)


if __name__=='__main__':main()
