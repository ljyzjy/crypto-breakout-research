"""Evaluate frozen probabilities against same-period costed unit paths."""
import hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
def main():
    year=sys.argv[1] if len(sys.argv)>1 else '2024';assert year in ('2024','2026')
    period='2024_may_jun' if year=='2024' else '2026_may_jul';folder=H/('2024后续比较批次' if year=='2024' else '2026后续比较批次')
    quality=json.loads((H/'事前预测质量.json').read_text(encoding='utf-8'))
    model=json.loads((H/'四月底固定模型.json').read_text(encoding='utf-8'))['models']
    assert hashlib.sha256((H/'事前固定预测.parquet').read_bytes()).hexdigest()==quality['score_sha256']
    audit=json.loads((folder/'动态池净账本独立核验.json').read_text(encoding='utf-8'));assert audit['verified_archive_manifests_matched']>0
    pred=pd.read_parquet(H/'事前固定预测.parquet');pred=pred[pred.period.eq(period)]
    ledger=pd.read_parquet(folder/'动态池单位收益与风险.parquet');assert not ledger.duplicated(['observation_id','variant']).any()
    output=[]
    for lev in (10,20):
        z=pred[pred.leverage.eq(lev)];scored=z[z.decision.isin(['selected','model_rejected'])]
        base=ledger[ledger.variant.eq(f'normal_2r_{lev}x')]
        joined=scored.merge(base,on='observation_id',how='left',validate='one_to_one')
        ok=joined.status.eq('verified')&joined.risk_status.eq('verified')&~joined.liq_proxy.fillna(False)
        v=joined[ok];p=v.model_probability.to_numpy(float);y=(v.net_per_unit_notional.to_numpy(float)>0).astype(int)
        if len(y):
            prior=model[str(lev)]['train_wins']/model[str(lev)]['train_events']
            brier=float(np.mean((p-y)**2));constant=float(np.mean((prior-y)**2))
            pos=p[y==1];neg=p[y==0]
            auc=float(((pos[:,None]>neg[None,:]).sum()+.5*(pos[:,None]==neg[None,:]).sum())/(len(pos)*len(neg))) if len(pos) and len(neg) else None
        else:prior=brier=constant=auc=None
        selected=v[v.decision.eq('selected')];net=selected.net_pct_notional.to_numpy(float)
        output.append({'leverage':lev,'scored_events':len(scored),'verified_scored_events':len(v),
          'scored_events_with_unverified_risk':int((~ok).sum()),'source_unknown_events':int(z.decision.eq('source_unknown').sum()),
          'observed_net_wins_in_scored_subset':int(y.sum()),'observed_net_win_rate_pct':float(100*y.mean()) if len(y) else None,
          'mean_model_probability':float(p.mean()) if len(p) else None,'brier_score':brier,
          'frozen_training_win_rate_probability':prior,'constant_training_rate_brier_score':constant,'descriptive_auc':auc,
          'verified_selected_trades':len(selected),'selected_mean_net_pct_notional':float(net.mean()) if len(net) else None})
    out={'period':period,'model_score_sha256':quality['score_sha256'],'rows':output,
         'note':'Calibration/ranking is descriptive on already explored periods and only risk-verified unit paths. Unknown data and account constraints remain.'}
    (folder/'模型历史预测诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('NETMODEL39_VALIDATION_DIAGNOSIS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
