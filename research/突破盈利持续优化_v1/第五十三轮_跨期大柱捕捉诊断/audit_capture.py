"""Independently reconcile deduplicated capture summaries and unknowns."""
import json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';Q=900_000
def main():
    assert json.loads((H/'跨期大柱行情样本核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    labels=pd.read_parquet(H/'跨期事后大柱标签.parquet');result=json.loads((H/'跨期大柱捕捉对照.json').read_text(encoding='utf-8'))
    comparison=json.loads((I/'comparison.json').read_text(encoding='utf-8'))['rows'];checks=[]
    for year in ('2024','2026'):
        l=labels[labels.source_year.eq(year)].copy();l['bar']=list(zip(l.contract,l.quarter_start.astype('int64'),l.allowed_side.astype('int64')))
        bybar={key:g for key,g in l.groupby('bar',sort=False)};large=set();label_unknown=set()
        for key,g in bybar.items():
            if not g.status.eq('verified').all():label_unknown.add(key);continue
            vals=set(g.large.astype(bool));assert len(vals)==1
            if True in vals:large.add(key)
        for lev in (10,20):
            b=pd.read_parquet(I/f'{year}_baseline_ledger.parquet');r=pd.read_parquet(I/f'{year}_retry_ledger.parquet')
            for strategy in ('baseline','single_retest'):
                prior=next(x for x in comparison if x['year']==year and x['leverage']==lev and x['strategy']==strategy)
                ledger=pd.concat([b] if strategy=='baseline' else [b,r],ignore_index=True)
                ledger=ledger[ledger.variant.eq(f'normal_2r_{lev}x')&ledger.observation_id.isin(prior['verified_observation_ids'])]
                joined=l.merge(ledger[['observation_id','entry_ts','side']],on='observation_id',how='inner',validate='one_to_one')
                success=set(joined.loc[(joined.side==joined.allowed_side)&(joined.entry_ts<joined.quarter_start+Q),'bar'])&large
                uncertain=set(l.loc[l.observation_id.isin(prior['unknown_observation_ids']),'bar'])&large-success
                row=next(x for x in result['rows'] if x['year']==year and x['leverage']==lev and x['strategy']==strategy)
                assert row['candidate_events']==len(l) and row['distinct_candidate_bars']==len(bybar) and row['unknown_label_bars']==len(label_unknown)
                assert row['verified_large_bars']==len(large) and row['verified_captured_bars']==len(success) and row['unknown_capture_bars']==len(uncertain)
                if large:
                    assert math.isclose(row['capture_pct'],100*len(success)/len(large),rel_tol=1e-11)
                    assert math.isclose(row['optimistic_capture_pct'],100*(len(success)+len(uncertain))/len(large),rel_tol=1e-11)
                checks.append({'year':year,'leverage':lev,'strategy':strategy,'large':len(large),'captures':len(success),'unknown':len(uncertain)})
    out={'all_checks_pass':True,'groups':checks,'note':'Unique candidate bars only; labels are only known after close.'}
    (H/'跨期大柱捕捉独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE53_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
