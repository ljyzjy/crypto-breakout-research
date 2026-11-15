"""Post-close labeling of frozen unit paths, preserving uncertain source events."""
import hashlib,json
from decimal import Decimal
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;INP=HERE/'冻结输入'

def main():
    frozen=json.loads((HERE/'冻结输入哈希.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256']==hashlib.sha256((HERE/'事后诊断方案.md').read_bytes()).hexdigest()
    for name,item in frozen['sources'].items():assert hashlib.sha256((INP/name).read_bytes()).hexdigest()==item['sha256']
    s=pd.read_parquet(INP/'baseline_signal.parquet');f=pd.read_parquet(INP/'follow_signal.parquet')
    assert s.observation_id.is_unique and f.observation_id.is_unique and set(s.observation_id)==set(f.observation_id)
    bars=pd.read_parquet(HERE/'候选十五分钟行情.parquet');assert not bars.duplicated(['contract','open_time']).any()
    audit=json.loads((HERE/'十五分钟行情样本独立核验.json').read_text(encoding='utf-8'))
    suspect={(x['contract'],int(x['quarter_start'])) for x in audit['samples'] if x['status']!='verified'}
    events=s.merge(bars[['contract','open_time','open','close','volume']],left_on=['contract','quarter_start'],
                   right_on=['contract','open_time'],how='left',validate='one_to_one')
    label={};missing=set();directions={}
    for r in events.itertuples(index=False):
        key=(r.contract,int(r.quarter_start))
        if key in suspect or pd.isna(r.open) or pd.isna(r.close) or pd.isna(r.volume) or float(r.volume)<=0:
            missing.add(r.observation_id);continue
        op=Decimal(str(r.open));cl=Decimal(str(r.close));change=(cl-op)/op
        direction=1 if change>0 else (-1 if change<0 else 0)
        eligible=(direction==1 and bool(r.long_known_eligible)) or (direction==-1 and bool(r.short_known_eligible))
        label[r.observation_id]=(abs(change)>=Decimal('0.01') and eligible)
        directions[r.observation_id]=direction
    large={obs for obs,v in label.items() if v};byid={r.observation_id:r for r in s.itertuples(index=False)}
    benign={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified','no_follow_known'}
    experiments=[('baseline',False,10),('baseline',False,20),('baseline',True,10),('baseline',True,20),
                 ('follow',False,10),('follow',False,20)]
    cache={}
    for name in ('baseline','follow'):
        sig=pd.read_parquet(INP/f'{name}_signal.parquet');paths=pd.read_parquet(INP/f'{name}_paths.parquet')
        ledger=pd.read_parquet(INP/f'{name}_ledger.parquet')
        assert not paths.duplicated(['observation_id','variant']).any() and not ledger.duplicated(['observation_id','variant']).any()
        cache[name]=(sig,paths,ledger)
    rows=[]
    for name,phase,lev in experiments:
        sig,paths,ledger=cache[name];variant=f'normal_2r_{lev}x';pp=paths[paths.variant.eq(variant)];ll=ledger[ledger.variant.eq(variant)]
        unknown=set(sig.loc[~sig.status.isin(benign),'observation_id'])
        unknown|=set(pp.loc[~pp.status.eq('verified'),'observation_id'])
        good=ll[ll.status.eq('verified')&ll.risk_status.eq('verified')&~ll.liq_proxy.fillna(False)].copy()
        unknown|=set(ll.loc[~(ll.status.eq('verified')&ll.risk_status.eq('verified')&~ll.liq_proxy.fillna(False)),'observation_id'])
        unknown-=set(good.observation_id)
        if phase:
            good=good[good.apply(lambda x:int(x.decision_ts)-int(byid[x.observation_id].quarter_start)>=10_000,axis=1)]
        classified=good[good.observation_id.isin(label)]
        matched=[]
        for r in classified.itertuples(index=False):
            e=byid[r.observation_id]
            if label[r.observation_id] and int(r.side)==directions[r.observation_id] and int(r.entry_ts)<int(e.quarter_end):matched.append(r)
        possible=unknown&large
        assert not (possible&{r.observation_id for r in matched})
        wins=sum(float(r.net_pct_notional)>0 for r in matched)
        values=[float(r.net_pct_notional) for r in matched]
        matched_ids={r.observation_id for r in matched}
        other=[r for r in classified.itertuples(index=False) if r.observation_id not in matched_ids]
        other_values=[float(r.net_pct_notional) for r in other]
        rows.append({'strategy':name,'exclude_first_10_seconds':phase,'leverage':lev,
          'verified_entries':len(good),'verified_entries_with_bar_label':len(classified),
          'large_direction_entries':len(matched),'large_direction_entries_net_positive':wins,
          'large_direction_entries_mean_net_pct_notional':float(np.mean(values)) if values else None,
          'other_classified_entries':len(other),'other_classified_entries_net_positive':sum(x>0 for x in other_values),
          'other_classified_entries_mean_net_pct_notional':float(np.mean(other_values)) if other_values else None,
          'large_entry_share_of_classified_entries_pct':100*len(matched)/len(classified) if len(classified) else None,
          'large_candidate_count':len(large),'observed_large_candidate_entry_rate_pct':100*len(matched)/len(large) if large else None,
          'unknown_large_candidates':len(possible),
          'optimistic_large_candidate_entry_upper_pct':100*(len(matched)+len(possible))/len(large) if large else None})
    out={'candidate_events':len(s),'classified_candidate_quarters':len(label),'unclassified_candidate_quarters':len(missing),
         'candidate_large_quarters':len(large),'sample_checks_passed':audit['sample_pass'],'sample_checks_total':audit['sample_count'],
         'rows':rows,'note':'Post-close 1% body label only. Candidate-cohort rates are not market-wide recall or shared-account fills.'}
    (HERE/'大突破柱捕捉事后诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE38_DIAGNOSIS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
