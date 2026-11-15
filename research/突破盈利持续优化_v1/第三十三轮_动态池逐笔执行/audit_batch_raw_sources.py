"""Check every training-batch raw reconciliation and preservation of original flags."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
def main():
    backup='--backup' in sys.argv;folder=(HERE.parent/'第三十四轮_历史候选动态替补'/'训练期分批' if backup else HERE/'训练期分批')
    refs=json.loads((folder/'严格原始成交复核来源.json').read_text(encoding='utf-8'))
    signal=pd.read_parquet(folder/'动态池逐笔信号筛查.parquet').set_index('observation_id')
    paths=pd.read_parquet(folder/'动态池延迟市价路径.parquet')
    if len(paths):paths=paths.set_index(['observation_id','variant'])
    rawroots={(ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation').resolve()};original={}
    taperoots=[ROOT/'work'/'point_in_time_universe33'/'tape']
    if backup:
        rawroots.add((ROOT/'work'/'point_in_time_universe34'/'raw_reconciliation').resolve())
        taperoots.append(ROOT/'work'/'point_in_time_universe34'/'tape')
    for taperoot in taperoots:
      for f in taperoot.glob('*.json'):
        z=json.loads(f.read_text(encoding='utf-8'))
        for row in z['rows']:
            if row.get('status')=='minute_trade_ohlc_mismatch':original[row['observation_id']]=z
    checks=0;pathchecks=0
    for ref in refs:
        obs=ref['observation_id'];assert obs in original
        path=Path(ref['checkpoint']).resolve();assert path.parent in rawroots and path.exists()
        batch=json.loads(path.read_text(encoding='utf-8'));item=next(x for x in batch['rows'] if x['observation_id']==obs)
        assert item['reconciled'] and item['raw_matches_kline'] and item['aggregate_open_only']
        assert np.allclose(item['aggregate_flow'],item['raw_flow'],rtol=1e-9,atol=1e-8)
        archived={(x['kind'],x['day']):x['sha256'] for x in batch['archives']}
        old={(x['kind'],x['day']):x['sha256'] for x in original[obs]['archives']}
        assert all(archived[k]==v for k,v in old.items())
        assert any(k[0]=='trades' for k in archived)
        outcome=item['outcome'];got=signal.loc[obs]
        assert got.original_source_status=='minute_trade_ohlc_mismatch' and got.source_resolution=='strict_raw_reconciliation'
        assert got.status==outcome['status']
        if outcome['status']=='qualified':
            assert set(item['paths_checked'])==set(outcome['paths'])
            for v,p in outcome['paths'].items():
                actual=paths.loc[(obs,v)];assert p['status']==actual.status
                for k in ('entry_ts','exit_signal_ts','exit_ts','reason'):
                    if k in p:assert p[k]==actual[k]
                for k in ('entry_raw','entry_fill','exit_raw','exit_fill'):
                    if k in p:assert np.isclose(p[k],actual[k],rtol=1e-11,atol=1e-12)
                pathchecks+=1
        checks+=1
    out={'backup_training':backup,'strictly_resolved_events_checked':checks,'resolved_variant_paths_checked':pathchecks,
         'original_mismatch_flags_preserved':True,'original_aggregate_and_kline_sha_match':True,
         'note':'Checks retained reconciliations and source hashes; unresolved events remain unknown.'}
    (folder/'严格原始复核独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_RAW_SOURCE_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
