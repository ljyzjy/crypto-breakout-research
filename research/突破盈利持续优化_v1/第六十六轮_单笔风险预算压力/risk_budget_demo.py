"""Illustrate per-trade sizing from pre-entry reference, not an account replay."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;R58=H.parent/'第五十八轮_一秒入场一倍止盈';BUDGET=.005
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    results=[];details=[];sources=[H/'诊断方案.md',Path(__file__)]
    for year in ('2024','2026'):
        I=R58/f'{year}冻结输入';manifest=R58/f'{year}输入冻结哈希.json';m=json.loads(manifest.read_text(encoding='utf-8'))
        assert all(sha(I/n)==v for n,v in m['inputs'].items());sources.extend([manifest,I/'events.parquet',I/'pair_details.parquet',I/'ledger_2r.parquet',I/'pair_summary.json'])
        events=pd.read_parquet(I/'events.parquet').set_index('observation_id');pairs=pd.read_parquet(I/'pair_details.parquet');ledger=pd.read_parquet(I/'ledger_2r.parquet');summary=json.loads((I/'pair_summary.json').read_text(encoding='utf-8'))['rows']
        assert events.index.is_unique
        for lev in (10,20):
            ref=next(x for x in summary if x['leverage']==lev);d=pairs[pairs.leverage.eq(lev)];old=ledger[ledger.variant.eq(f'one_second_2r_{lev}x')].set_index('observation_id')
            assert len(d)==ref['paired_verified'];result=[]
            for r in d.itertuples(index=False):
                e=events.loc[r.observation_id];x=old.loc[r.observation_id];assert x.risk_status=='verified' and not x.liq_proxy
                side=int(e.side);reference=float(e.raw_entry_5s);stop=float(e.stop_price)
                assert int(e.entry_exec_ts)<=int(x.entry_ts) and side==int(x.side) and abs(float(x.net_per_unit_notional)-r.one_second_net)<1e-12
                entry_est=reference*(1+side*.0005);stop_est=stop*(1-side*.0005)
                planned_cash_loss=-(side*(stop_est-entry_est)-.0005*entry_est-.0005*stop_est)
                if not np.isfinite(planned_cash_loss) or planned_cash_loss<=0:raise ValueError('nonpositive_planned_loss')
                qty_risk=BUDGET/planned_cash_loss;qty_cash=1/(entry_est*(1/lev+.0005));quantity=min(qty_risk,qty_cash)
                planned_loss=quantity*planned_cash_loss;estimated_cost=quantity*entry_est*(1/lev+.0005)
                realized_equity_fraction=quantity*float(x.entry_fill)*float(x.net_per_unit_notional)
                actual_initial_cost=quantity*float(x.entry_fill)*(1/lev+.0005)
                assert planned_loss<=BUDGET+1e-12 and estimated_cost<=1+1e-12
                item={'year':year,'leverage':lev,'observation_id':r.observation_id,'side':side,'reference':reference,'stop':stop,
                      'estimated_entry':entry_est,'estimated_stop_fill':stop_est,'quantity_per_initial_equity':quantity,
                      'planned_loss_fraction_equity':planned_loss,'estimated_initial_cost_fraction':estimated_cost,
                      'actual_initial_cost_fraction':actual_initial_cost,'realized_fraction_equity':realized_equity_fraction,
                      'reason':x.reason,'net_per_unit_notional':float(x.net_per_unit_notional)}
                result.append(item);details.append(item)
            actual=np.array([x['realized_fraction_equity'] for x in result]);planned=np.array([x['planned_loss_fraction_equity'] for x in result]);n=len(actual)
            results.append({'year':year,'leverage':lev,'verified_trades':n,'original_unknown':ref['paired_unknown'],
                'risk_budget_pct_equity':100*BUDGET,'loss_over_budget_count':int((actual< -BUDGET-1e-12).sum()),
                'cash_cap_binding_count':sum(x['estimated_initial_cost_fraction']>=1-1e-12 for x in result),
                'realized_initial_cost_over_equity_count':sum(x['actual_initial_cost_fraction']>1+1e-12 for x in result),
                'risk_budget_breach_fill_count':sum(x['reason']=='filled_beyond_risk_budget' for x in result),
                'mean_planned_loss_pct_equity':100*float(planned.mean()) if n else None,
                'worst_actual_result_pct_equity':100*float(actual.min()) if n else None,
                'mean_actual_result_pct_equity':100*float(actual.mean()) if n else None})
    out={'rows':results,'source_sha256':{str(p):sha(p) for p in sources},
         'note':'Illustrative independent trades, planned from known reference; no shared-account sequence, actual exchange or guaranteed loss cap.'}
    (H/'单笔风险预算情景.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(details).to_csv(H/'单笔风险预算逐笔.csv',index=False,encoding='utf-8-sig')
    print('RISK_BUDGET66',json.dumps(results,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
