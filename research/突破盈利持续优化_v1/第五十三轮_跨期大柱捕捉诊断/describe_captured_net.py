"""Describe net outcomes of verified entries into post-close big candles."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';Q=900_000
def main():
    assert json.loads((H/'跨期大柱捕捉独立核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    labels=pd.read_parquet(H/'跨期事后大柱标签.parquet');capture=json.loads((H/'跨期大柱捕捉对照.json').read_text(encoding='utf-8'))['rows']
    prior=json.loads((I/'comparison.json').read_text(encoding='utf-8'))['rows'];out=[];detail=[]
    for year in ('2024','2026'):
        x=labels[labels.source_year.eq(year)&labels.status.eq('verified')&labels.large.eq(True)].copy()
        x['bar']=list(zip(x.contract,x.quarter_start.astype('int64'),x.allowed_side.astype('int64')))
        base=pd.read_parquet(I/f'{year}_baseline_ledger.parquet');retry=pd.read_parquet(I/f'{year}_retry_ledger.parquet')
        for strategy in ('baseline','single_retest'):
            summary=next(z for z in prior if z['year']==year and z['strategy']==strategy and z['leverage']==20)
            frames=[base] if strategy=='baseline' else [base,retry];ledger=pd.concat(frames,ignore_index=True)
            ledger=ledger[ledger.variant.eq('normal_2r_20x')&ledger.observation_id.isin(summary['verified_observation_ids'])]
            d=x.merge(ledger[['observation_id','entry_ts','exit_ts','side','net_per_unit_notional']],on='observation_id',how='inner',validate='one_to_one')
            d=d[(d.side==d.allowed_side)&(d.entry_ts<d.quarter_start+Q)].sort_values(['entry_ts','observation_id']).drop_duplicates('bar')
            reference=next(z for z in capture if z['year']==year and z['strategy']==strategy and z['leverage']==20)
            assert len(d)==reference['verified_captured_bars'];v=d.net_per_unit_notional.to_numpy(float);assert np.isfinite(v).all()
            pos=float(v[v>0].sum());neg=float(-v[v<0].sum());n=len(d)
            out.append({'year':year,'strategy':strategy,'known_large_bars':reference['verified_large_bars'],'captured':n,
                        'capture_unknown':reference['unknown_capture_bars'],'net_wins':int((v>0).sum()),
                        'net_win_rate_pct':100*int((v>0).sum())/n if n else None,'mean_net_pct_notional':100*float(v.mean()) if n else None,
                        'profit_factor':pos/neg if neg else None,'held_through_close':int((d.exit_ts>=d.quarter_start+Q).sum()),
                        'median_entry_seconds_after_candle_start':float(((d.entry_ts-d.quarter_start)/1000).median()) if n else None})
            detail.extend({'year':year,'strategy':strategy,'observation_id':r.observation_id,'quarter_start':int(r.quarter_start),
                           'entry_ts':int(r.entry_ts),'exit_ts':int(r.exit_ts),'net':float(r.net_per_unit_notional)} for r in d.itertuples(index=False))
    pd.DataFrame(detail).to_parquet(H/'大柱入场后净结果明细.parquet',index=False)
    z={'plan_sha256':hashlib.sha256((H/'大柱入场后净结果_诊断方案.md').read_bytes()).hexdigest(),'rows':out,
       'note':'Conditioned after candle close; full trade net, not profit over candle or account results.'}
    (H/'大柱入场后净结果.json').write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE53_NET',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
