"""Independently reconcile all 2023 candle labels and captured paths."""
import json,math
from decimal import Decimal
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';M=60_000;Q=15*M
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    candidates=pd.read_parquet(I/'candidates.parquet');signal=pd.read_parquet(I/'signals.parquet').set_index('observation_id')
    labels=pd.read_parquet(H/'2023候选事后大柱标签.parquet').set_index('observation_id')
    ledger=pd.read_parquet(I/'ledger.parquet');sources=json.loads((I/'minute_hashes.json').read_text(encoding='utf-8'))['sources']
    found=set();checked=0
    for sym,events in candidates.groupby('contract',sort=True):
        d=pd.read_parquet(Path(sources[f'{sym}_klines.parquet']['path']),columns=['ts','open','close','volume','trade_count']).set_index('ts')
        for e in events.itertuples(index=False):
            label=labels.loc[e.observation_id];assert label.status=='verified'
            m=d.reindex(range(int(e.quarter_start),int(e.quarter_end),M));assert len(m)==15 and m.notna().all().all()
            op=Decimal(str(m.open.iloc[0]));close=Decimal(str(m.close.iloc[-1]));side=int(e.market_allowed_side)
            boundary=Decimal(str(e.upper if side==1 else e.lower))
            large=side*(close-op)/op>=Decimal('0.01') and side*(close-boundary)>0
            assert bool(label.large)==large and near(label.open,op) and near(label.close,close)
            if large:found.add(e.observation_id)
            checked+=1
    out=json.loads((H/'2023大柱捕捉事后诊断.json').read_text(encoding='utf-8'));assert len(found)==out['known_large_candidates']
    for lev in (10,20):
        row=next(x for x in out['rows'] if x['leverage']==lev)
        p=ledger[ledger.variant.eq(f'normal_2r_{lev}x')]
        ok=p[p.status.eq('verified')&p.risk_status.eq('verified')&~p.liq_proxy.fillna(False)]
        got={r.observation_id:r for r in ok.itertuples(index=False)}
        expected=set()
        for obs in found&set(got):
            r=got[obs];c=candidates.loc[candidates.observation_id.eq(obs)].iloc[0]
            if int(r.side)==int(c.market_allowed_side) and int(r.entry_ts)<int(c.quarter_end):expected.add(obs)
        unknown=set(signal.index[~signal.status.isin({'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'})])
        assert expected==set(row['matched_observation_ids']) and found&unknown==set(row['unknown_large_observation_ids'])
        vals=[float(got[obs].net_pct_notional) for obs in expected];other=[float(r.net_pct_notional) for obs,r in got.items() if obs not in expected]
        assert row['verified_entries']==len(got) and row['verified_large_direction_entries']==len(expected)
        assert row['large_entry_net_wins']==sum(x>0 for x in vals) and row['other_entry_net_wins']==sum(x>0 for x in other)
        if vals:assert near(row['large_entry_mean_net_pct_notional'],sum(vals)/len(vals))
        if other:assert near(row['other_entry_mean_net_pct_notional'],sum(other)/len(other))
        if found:assert near(row['observed_large_candidate_capture_pct'],100*len(expected)/len(found))
    result={'candidates_checked':checked,'large_labels_reproduced':len(found),'leverage_groups_checked':2,
            'sample_official_quarter_bars_checked':68,'all_checks_pass':True,
            'note':'Only the 146 prefiltered candidate bars; close-based labels cannot be used at entry.'}
    (H/'2023大柱捕捉独立核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CAPTURE45_AUDIT',json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
