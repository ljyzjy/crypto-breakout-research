"""Regression checks for all mapped symbols, especially 1000-unit contracts."""
from pathlib import Path
import json
import pandas as pd
from account_market import load_symbol_hourly, PoolCorrelationGuard
from market_io import load_mapping, PHASE2

ROOT=Path(__file__).resolve().parent


def main():
    local=ROOT/'synthetic_mapping'
    local.mkdir(exist_ok=True)
    tests=[]
    for symbol,contract in [('PEPEUSDT','1000PEPEUSDT'),('BONKUSDT','1000BONKUSDT'),('SHIBUSDT','1000SHIBUSDT')]:
        pd.DataFrame({'ts':[0,3_600_000],'symbol':[symbol]*2,'contract':[contract]*2,
                      'hourly_return':[0.,.01]}).to_parquet(local/f'{symbol}.parquet',index=False)
        d=load_symbol_hourly(symbol,contract,['ts','hourly_return'],local)
        assert len(d)==2 and d.contract.eq(contract).all()
        assert not (local/f'{contract}.parquet').exists()
        tests.append('synthetic_'+symbol+'_reads_symbol_shard_preserves_contract')
    try:load_symbol_hourly('MISSINGUSDT','1000MISSINGUSDT',['ts'],local)
    except FileNotFoundError:tests.append('mapped_missing_file_raises_instead_of_skip')
    else:raise AssertionError('Missing mapped symbol silently accepted')
    try:load_symbol_hourly('PEPEUSDT','WRONGUSDT',['ts'],local)
    except ValueError:tests.append('internal_contract_identity_mismatch_raises')
    else:raise AssertionError('Wrong contract identity silently accepted')
    mapping={s:c for s,c in load_mapping().items() if c}
    rows=[]
    for symbol,contract in mapping.items():
        d=load_symbol_hourly(symbol,contract,['ts','hourly_return'])
        rows.append({'symbol':symbol,'contract':contract,'hourly_rows':len(d),'internal_identity_pass':True})
    regimes=pd.read_parquet(ROOT/'regimes.parquet')
    guard=PoolCorrelationGuard()
    assert set(regimes.symbol)==set(mapping)
    assert set(guard.h.columns)==set(mapping)
    ranks=pd.read_parquet(ROOT/'hourly-ranks.parquet')
    assert len(mapping)==60
    for symbol in ['PEPEUSDT','BONKUSDT','SHIBUSDT']:
        assert ranks.symbol.eq(symbol).any()
    tests.extend(['all_60_real_hourly_shard_identities','all_60_real_ema_symbols','all_60_real_correlation_symbols','three_1000_assets_have_actual_rank_rows'])
    output={'passed':len(tests),'tests':tests,'mapped_symbols':len(mapping),
        'rank_rows':len(ranks),'regime_symbols':regimes.symbol.nunique(),
        'correlation_symbols':len(guard.h.columns),
        'thousand_unit_rank_rows':ranks[ranks.symbol.isin(['PEPEUSDT','BONKUSDT','SHIBUSDT'])].groupby('symbol').size().to_dict(),
        'real_shard_identity_audit':rows}
    (ROOT/'mapped_asset_checks.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!='real_shard_identity_audit'}))


if __name__=='__main__':main()
