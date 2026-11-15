"""Reconcile frozen price-extension selection with audited source ledgers."""
import hashlib,json,math
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入';P=H.parent/'第四十七轮_一次重新突破确认'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def near(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-11)
def main():
    f=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    result=json.loads((H/'价格延伸跨期单位对照.json').read_text(encoding='utf-8'))['rows']
    prior=json.loads((P/'单次重试跨期单位对照.json').read_text(encoding='utf-8'))['rows'];details=pd.read_parquet(H/'价格延伸已核验明细.parquet');checks=[]
    for year in ('2023','2024','2026'):
        b=pd.read_parquet(I/f'{year}_baseline_signal.parquet').set_index('observation_id')
        r=pd.read_parquet(I/f'{year}_retry_signal.parquet').set_index('observation_id')
        led=pd.concat([pd.read_parquet(I/f'{year}_baseline_ledger.parquet'),pd.read_parquet(I/f'{year}_retry_ledger.parquet')],ignore_index=True)
        for lev in (10,20):
            original=next(x for x in result if x['year']==year and x['leverage']==lev and x['strategy']=='original')
            chosen=next(x for x in result if x['year']==year and x['leverage']==lev and x['strategy']=='extension_005pct')
            prev=next(x for x in prior if x['year']==year and x['leverage']==lev and x['strategy']=='single_retest')
            assert set(original['verified_ids'])==set(prev['verified_observation_ids']) and set(original['unknown_ids'])==set(prev['unknown_observation_ids'])
            selected={}
            for obs in original['verified_ids']:
                e=r.loc[obs] if obs in r.index else b.loc[obs];move=int(e.side)*(float(e.raw_entry_5s)/float(e.signal_close)-1)
                assert int(e.entry_exec_ts)>=int(e.decision_ts)+5000
                if move>=.0005:selected[obs]=move
            d=details[(details.year.astype(str)==year)&(details.leverage==lev)].set_index('observation_id')
            assert set(d.index)==set(selected)==set(chosen['verified_ids'])
            ll=led[led.variant.eq(f'normal_2r_{lev}x')].set_index('observation_id')
            for obs,move in selected.items():assert near(d.loc[obs,'extension'],move) and near(d.loc[obs,'net'],ll.loc[obs,'net_per_unit_notional'])
            vals=d.net.astype(float);n=len(vals);wins=int((vals>0).sum());u=chosen['possible_unknown_events']
            assert chosen['candidate_events']==chosen['known_no_order']+u+n and chosen['verified_wins']==wins
            if n:assert near(chosen['net_win_rate_pct'],100*wins/n) and near(chosen['mean_net_pct_notional'],100*vals.mean())
            if n+u:assert near(chosen['optimistic_unit_win_upper_pct'],100*(wins+u)/(n+u))
            checks.append({'year':year,'leverage':lev,'selected':n,'wins':wins,'unknown':u})
    out={'all_checks_pass':True,'groups':checks,'note':'Pre-entry extension selection and net results reconciled to frozen audited ledgers.'}
    (H/'价格延伸独立核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PRICE50_AUDIT',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
