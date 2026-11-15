"""Apply only independently reconciled no-order candidates to frozen capture bounds."""
import json
from decimal import Decimal
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent
def main():
    d=json.loads((H/'大突破柱捕捉事后诊断.json').read_text(encoding='utf-8'))
    resolved=json.loads((P/'第三十五轮_二次价格跟随'/'严格复核不下单敏感性结果.json').read_text(encoding='utf-8'))
    audit=json.loads((P/'第三十五轮_二次价格跟随'/'严格复核不下单敏感性独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass']
    sig=pd.read_parquet(H/'冻结输入'/'baseline_signal.parquet').set_index('observation_id')
    follow=pd.read_parquet(H/'冻结输入'/'follow_signal.parquet').set_index('observation_id')
    bars=pd.read_parquet(H/'候选十五分钟行情.parquet').set_index(['contract','open_time'])
    sample=json.loads((H/'十五分钟行情样本独立核验.json').read_text(encoding='utf-8'))
    suspect={(x['contract'],int(x['quarter_start'])) for x in sample['samples'] if x['status']!='verified'}
    big_noorder=[]
    for r in resolved['resolved_source_records']:
        obs=r['observation_id'];assert follow.loc[obs,'status']=='upstream_data_unknown'
        e=sig.loc[obs];key=(e.contract,int(e.quarter_start))
        if key not in bars.index or key in suspect:continue
        b=bars.loc[key]
        if b.volume<=0:continue
        op=Decimal(str(b.open));cl=Decimal(str(b.close));delta=cl-op;side=1 if delta>0 else -1 if delta<0 else 0
        eligible=(side==1 and e.long_known_eligible) or (side==-1 and e.short_known_eligible)
        if abs(delta)>=Decimal('.01')*op and eligible:big_noorder.append(obs)
    assert len(big_noorder)==len(set(big_noorder))
    rows=[]
    for row in d['rows']:
        if row['strategy']!='follow':continue
        unknown=row['unknown_large_candidates']-len(big_noorder);assert unknown>=0
        rows.append({'leverage':row['leverage'],'large_candidates':row['large_candidate_count'],
            'verified_large_entries':row['large_direction_entries'],'known_no_order_large_candidates':len(big_noorder),
            'remaining_unknown_large_candidates':unknown,
            'optimistic_large_candidate_entry_upper_pct':100*(row['large_direction_entries']+unknown)/row['large_candidate_count']})
    out={'resolved_no_order_large_observation_ids':big_noorder,'rows':rows,
         'note':'Frozen candidate cohort only; no account or market-wide inference.'}
    (H/'严格复核后大柱捕捉敏感性.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE38_NO_ORDER_SENSITIVITY',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
