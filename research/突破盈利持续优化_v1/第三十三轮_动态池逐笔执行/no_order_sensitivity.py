"""Identify source-disagreement cases that cannot pass the fixed direction filter."""
import hashlib,json
from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
def main():
    source=HERE.parent/'第三十二轮_历史动态池分钟信号'/'历史动态池潜在触价_待逐笔验证.parquet'
    cand=pd.read_parquet(source).set_index('observation_id');seen=set();rows=[];original={}
    for p in (ROOT/'work'/'point_in_time_universe33'/'tape').glob('*.json'):
        z=json.loads(p.read_text(encoding='utf-8'))
        for r in z['rows']:
            if r.get('status')=='minute_trade_ohlc_mismatch':original[r['observation_id']]=z
    for path in sorted((ROOT/'work'/'point_in_time_universe33'/'raw_reconciliation').glob('*.json')):
        batch=json.loads(path.read_text(encoding='utf-8'))
        if batch.get('status')!='verified':continue
        for x in batch['rows']:
            obs=x['observation_id']
            if obs in seen or x.get('reason')!='five_second_flow_mismatch':continue
            seen.add(obs);assert obs in original
            before={(a['kind'],a['day']):a['sha256'] for a in original[obs]['archives']}
            after={(a['kind'],a['day']):a['sha256'] for a in batch['archives']}
            assert all(after[k]==v for k,v in before.items())
            e=cand.loc[obs];long=bool(e.long_known_eligible);short=bool(e.short_known_eligible)
            if long==short:continue
            side=1 if long else -1;a=x['aggregate_flow'];r=x['raw_flow']
            if sum(a)<=0 or sum(r)<=0:continue
            ai=side*(a[0]-a[1])/sum(a);ri=side*(r[0]-r[1])/sum(r)
            if ai<.10 and ri<.10:
                rows.append({'observation_id':obs,'side_if_eligible':side,'aggregate_imbalance':ai,'raw_imbalance':ri,
                             'original_reason':'five_second_flow_mismatch','earlier_kline_prefix_verified':True,
                             'raw_checkpoint':str(path),'archives':batch['archives']})
    out={'conditional_both_sources_no_order':len(rows),'events':rows,
         'rule_sha256':hashlib.sha256((HERE/'双来源一致无单敏感性规则.json').read_bytes()).hexdigest(),
         'note':'A separate sensitivity result; strict source mismatch remains recorded and no account PnL is inferred.'}
    (HERE/'双来源一致无单敏感性.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('UNIVERSE33_NO_ORDER_SENSITIVITY',json.dumps({'cases':len(rows),'note':out['note']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
