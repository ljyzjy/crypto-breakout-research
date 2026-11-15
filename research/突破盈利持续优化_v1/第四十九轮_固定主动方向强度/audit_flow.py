"""Independently check selected IDs, flow and net-unit summaries."""
import hashlib,json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';P=H.parent/'第四十七轮_一次重新突破确认'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    frozen=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==frozen['plan_sha256']
    for n,v in frozen['inputs'].items():assert sha(I/n)==v
    result=json.loads((H/'强方向跨期单位对照.json').read_text(encoding='utf-8'))['rows']
    prior=json.loads((P/'单次重试跨期单位对照.json').read_text(encoding='utf-8'))['rows']
    detail=pd.read_parquet(H/'强方向筛选已核验明细.parquet');checks=[]
    for year in ('2023','2024','2026'):
        base=pd.read_parquet(I/f'{year}_baseline_signal.parquet').set_index('observation_id')
        retry=pd.read_parquet(I/f'{year}_retry_signal.parquet').set_index('observation_id')
        led=pd.concat([pd.read_parquet(I/f'{year}_baseline_ledger.parquet'),pd.read_parquet(I/f'{year}_retry_ledger.parquet')],ignore_index=True)
        for lev in (10,20):
            orig=next(x for x in result if x['year']==year and x['leverage']==lev and x['strategy']=='original_010')
            strong=next(x for x in result if x['year']==year and x['leverage']==lev and x['strategy']=='strong_030')
            reference=next(x for x in prior if x['year']==year and x['leverage']==lev and x['strategy']=='single_retest')
            assert set(orig['verified_ids'])==set(reference['verified_observation_ids']) and set(orig['unknown_ids'])==set(reference['unknown_observation_ids'])
            assert near(orig['net_win_rate_pct'],reference['verified_win_rate_pct']) and near(orig['mean_net_pct_notional'],reference['mean_net_pct_notional'])
            selected={}
            for obs in orig['verified_ids']:
                e=retry.loc[obs] if obs in retry.index else base.loc[obs]
                b=float(e.buy_notional);s=float(e.sell_notional);flow=int(e.side)*(b-s)/(b+s)
                assert near(flow,e.five_imbalance) and int(e.entry_exec_ts)>=int(e.decision_ts)+5000
                if flow>=.30:selected[obs]=flow
            d=detail[(detail.year.astype(str)==year)&(detail.leverage==lev)].set_index('observation_id')
            assert set(d.index)==set(selected)==set(strong['verified_ids'])
            ll=led[led.variant.eq(f'normal_2r_{lev}x')].set_index('observation_id')
            for obs,flow in selected.items():assert near(d.loc[obs,'flow'],flow) and near(d.loc[obs,'net'],ll.loc[obs,'net_per_unit_notional'])
            vals=d.net.astype(float);n=len(vals);wins=int((vals>0).sum());assert strong['verified_events']==n and strong['verified_wins']==wins
            assert strong['candidate_events']==strong['known_no_order']+strong['possible_unknown_events']+n
            if n:assert near(strong['net_win_rate_pct'],100*wins/n) and near(strong['mean_net_pct_notional'],100*vals.mean())
            if n+strong['possible_unknown_events']:
                assert near(strong['optimistic_unit_win_upper_pct'],100*(wins+strong['possible_unknown_events'])/(n+strong['possible_unknown_events']))
            checks.append({'year':year,'leverage':lev,'selected':n,'wins':wins,'unknown':strong['possible_unknown_events']})
    out={'all_checks_pass':True,'groups':checks,'note':'Threshold selection and net summaries independently reconciled to audited frozen ledgers.'}
    (H/'强方向筛选独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FLOW49_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
