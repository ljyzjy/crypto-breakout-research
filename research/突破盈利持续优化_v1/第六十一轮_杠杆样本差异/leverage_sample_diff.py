"""Trace differences between 10x and 20x known one-second unit samples."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;FAST=H.parent/'第五十一轮_缩短市价入场延迟'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    rows=[];sources=[Path(__file__)]
    for year in ('2024','2026'):
        pair=FAST/f'{year}一秒五秒逐笔配对结果.parquet';signal=FAST/f'{year}一秒入场分批'/'动态池逐笔信号筛查.parquet'
        audit=FAST/f'{year}一秒入场账本独立核验.json';sources.extend([pair,signal,audit]);assert json.loads(audit.read_text(encoding='utf-8'))['all_checks_pass']
        d=pd.read_parquet(pair);s=pd.read_parquet(signal).set_index('observation_id')
        a=d[d.leverage.eq(10)].set_index('observation_id');b=d[d.leverage.eq(20)].set_index('observation_id')
        assert a.index.is_unique and b.index.is_unique and s.index.is_unique
        common=sorted(set(a.index)&set(b.index));only10=sorted(set(a.index)-set(b.index));only20=sorted(set(b.index)-set(a.index))
        assert np.array_equal(a.loc[common,'one_second_net'].to_numpy(float),b.loc[common,'one_second_net'].to_numpy(float))
        extra=[]
        for lev,ids,table in ((10,only10,a),(20,only20,b)):
            for obs in ids:
                item=s.loc[obs];extra.append({'observation_id':obs,'known_at_leverage':lev,'one_second_net_pct_notional':100*float(table.loc[obs,'one_second_net']),
                    'five_second_net_pct_notional':100*float(table.loc[obs,'five_second_net']),
                    'precheck_10x':item['precheck_10x'],'precheck_20x':item['precheck_20x']})
        rows.append({'year':year,'known_10x':len(a),'known_20x':len(b),'common':len(common),'one_second_common_net_exactly_equal':True,'extras':extra})
    out={'rows':rows,'source_sha256':{str(p):sha(p) for p in sources},
         'note':'Post-hoc unit-sample arithmetic only; leverage and true liquidation risk differ.'}
    (H/'杠杆已知样本差异.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('LEVERAGE61',json.dumps(rows,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
