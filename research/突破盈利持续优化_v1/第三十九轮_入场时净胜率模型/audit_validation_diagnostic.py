"""Recompute scored-subset outcomes, Brier score, AUC and unknown counts."""
import hashlib,json,math,sys
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-11,abs_tol=1e-12)
def main():
    yr=sys.argv[1] if len(sys.argv)>1 else '2024';assert yr in ('2024','2026')
    period='2024_may_jun' if yr=='2024' else '2026_may_jul';f=H/('2024后续比较批次' if yr=='2024' else '2026后续比较批次')
    reported=json.loads((f/'模型历史预测诊断.json').read_text(encoding='utf-8'))
    model=json.loads((H/'四月底固定模型.json').read_text(encoding='utf-8'))['models']
    assert hashlib.sha256((H/'事前固定预测.parquet').read_bytes()).hexdigest()==reported['model_score_sha256']
    scores=[x for x in pd.read_parquet(H/'事前固定预测.parquet').to_dict('records') if x['period']==period]
    ledger=pd.read_parquet(f/'动态池单位收益与风险.parquet').to_dict('records');groups=[]
    for row in reported['rows']:
        lev=row['leverage'];picks=[x for x in scores if x['leverage']==lev];scored=[x for x in picks if x['decision'] in ('selected','model_rejected')]
        ledger_by_id={x['observation_id']:x for x in ledger if x['variant']==f'normal_2r_{lev}x'}
        pairs=[];missing=0
        for s in scored:
            r=ledger_by_id.get(s['observation_id'])
            if not r or r['status']!='verified' or r['risk_status']!='verified' or r['liq_proxy']:missing+=1;continue
            side=int(r['side']);en=r['entry_raw']*(1+side*.0005);ex=r['exit_raw']*(1-side*.0005)
            net=side*(ex/en-1)-.0005-.0005*ex/en-r['funding'];assert near(net,r['net_per_unit_notional'])
            pairs.append((float(s['model_probability']),int(net>0),s['decision']))
        n=len(pairs);wins=sum(y for _,y,_ in pairs);unknown=sum(x['decision']=='source_unknown' for x in picks)
        assert row['scored_events']==len(scored) and row['verified_scored_events']==n and row['scored_events_with_unverified_risk']==missing
        assert row['source_unknown_events']==unknown and row['observed_net_wins_in_scored_subset']==wins
        if n:
            pmean=sum(p for p,_,_ in pairs)/n;brier=sum((p-y)**2 for p,y,_ in pairs)/n
            prior=model[str(lev)]['train_wins']/model[str(lev)]['train_events']
            cbrier=sum((prior-y)**2 for _,y,_ in pairs)/n
            assert near(row['observed_net_win_rate_pct'],100*wins/n) and near(row['mean_model_probability'],pmean)
            assert near(row['brier_score'],brier) and near(row['constant_training_rate_brier_score'],cbrier)
            pos=[p for p,y,_ in pairs if y];neg=[p for p,y,_ in pairs if not y]
            if pos and neg:
                auc=sum(1 if a>b else .5 if a==b else 0 for a in pos for b in neg)/(len(pos)*len(neg))
                assert near(row['descriptive_auc'],auc)
        assert row['verified_selected_trades']==sum(dec=='selected' for _,_,dec in pairs)
        groups.append({'leverage':lev,'verified_scored':n,'net_wins':wins,'unknown_sources':unknown})
    out={'period':period,'groups':groups,'brier_auc_and_fee_formula_checked':True,'all_checks_pass':True,
         'note':'No market-wide, account or prospective inference follows from these explored historical samples.'}
    (f/'模型历史预测独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('NETMODEL39_VALIDATION_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
