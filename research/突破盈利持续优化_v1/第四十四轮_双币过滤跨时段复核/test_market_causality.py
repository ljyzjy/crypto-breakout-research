"""Boundary, missingness and future-bar perturbation tests for the market filter."""
import json
from pathlib import Path
import pandas as pd
from market_decisions import classify,Q
H=Path(__file__).resolve().parent
def main():
    q=21*Q;lookup={}
    for sym in ('BTCUSDT','ETHUSDT'):
        for i in range(21):lookup[(sym,i*Q)]={'count':3 if i==20 else 2,'open':100.,'close':101.,'volume':1.}
    assert classify(q,lookup,set())['market_status']=='allowed' # 40*3 == 3*40
    lookup[('ETHUSDT',20*Q)]['count']=2
    assert classify(q,lookup,set())['market_status']=='known_no_order'
    del lookup[('BTCUSDT',0)]
    assert classify(q,lookup,set())['market_status']=='known_no_order' # a known failure is enough
    lookup[('ETHUSDT',20*Q)]['count']=3
    assert classify(q,lookup,set())['market_status']=='market_unknown'
    bars=pd.read_parquet(H/'BTC_ETH过去十五分钟数据.parquet');mapping={(r['symbol'],int(r['open_time'])):r for r in bars.to_dict('records')}
    sample=json.loads((H/'BTC_ETH一分钟样本核验.json').read_text(encoding='utf-8'))
    bad={(x['symbol'],int(x['open_time'])) for x in sample['samples'] if x['status']!='verified'}
    qs=sorted(set(map(int,pd.read_parquet(H/'冻结输入'/'baseline_signal.parquet').quarter_start)))
    checked=0
    for q in qs:
        before=classify(q,mapping,bad);saved={}
        for sym in ('BTCUSDT','ETHUSDT'):
            for t in (q,q+Q):
                key=(sym,t);saved[key]=mapping.get(key)
                mapping[key]={'count':999999999,'open':1.,'close':10**9,'volume':1.}
        after=classify(q,mapping,bad);assert before==after
        for key,value in saved.items():
            if value is None:del mapping[key]
            else:mapping[key]=value
        checked+=1
    out={'equality_threshold_checked':True,'known_failure_with_other_missing_checked':True,'missingness_remains_unknown':True,
         'unique_quarters_future_bars_perturbed':checked,'current_and_future_bar_perturbations_unchanged':True,'all_checks_pass':True}
    (H/'事前市场过滤时序核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL42_CAUSALITY_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
