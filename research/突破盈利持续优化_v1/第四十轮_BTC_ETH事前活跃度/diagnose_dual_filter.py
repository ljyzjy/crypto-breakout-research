"""Apply the frozen prior-closed BTC/ETH filter to verified training paths."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def main():
    f=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()==f['plan_sha256']
    for name,v in f['inputs'].items():assert hashlib.sha256((I/name).read_bytes()).hexdigest()==v
    causal=json.loads((H/'事前市场过滤时序核验.json').read_text(encoding='utf-8'));assert causal['all_checks_pass']
    quality=json.loads((H/'事前市场过滤质量.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'候选事前市场过滤.parquet').read_bytes()).hexdigest()==quality['decision_sha256']
    s=pd.read_parquet(I/'baseline_signal.parquet');d=pd.read_parquet(H/'候选事前市场过滤.parquet');ledger=pd.read_parquet(I/'baseline_ledger.parquet')
    assert s.observation_id.is_unique and d.observation_id.is_unique
    events=s.merge(d,on=['observation_id','quarter_start'],validate='one_to_one');assert len(events)==len(s)
    output=[]
    for lev in (10,20):
        variant=f'normal_2r_{lev}x';l=ledger[ledger.variant.eq(variant)];assert l.observation_id.is_unique
        path={r['observation_id']:r for r in l.to_dict('records')};good=[];unknown=set();noorder=0
        for e in events.to_dict('records'):
            obs=e['observation_id'];status=e['status'];market=e['market_status'];side=int(e['allowed_side'])
            if market=='known_no_order':noorder+=1;continue
            if status not in BENIGN:
                possible=(market=='market_unknown' or (side==1 and bool(e['long_known_eligible'])) or (side==-1 and bool(e['short_known_eligible'])))
                if possible:unknown.add(obs)
                else:noorder+=1
                continue
            if status!='qualified':noorder+=1;continue
            pre=e.get(f'precheck_{lev}x')
            if pd.isna(pre):unknown.add(obs);continue
            if pre!='passed':noorder+=1;continue
            if market=='market_unknown':unknown.add(obs);continue
            if int(e['side'])!=side:noorder+=1;continue
            r=path.get(obs)
            if not r or r['status']!='verified' or r['risk_status']!='verified' or r['liq_proxy']:
                unknown.add(obs);continue
            assert int(r['decision_ts'])>=int(e['quarter_start']) and int(r['entry_ts'])>=int(r['decision_ts'])+10_000
            good.append(r)
        n=len(good);x=np.array([r['net_per_unit_notional'] for r in good],float);assert np.isfinite(x).all()
        wins=int((x>0).sum());pos=float(x[x>0].sum());neg=float(-x[x<0].sum());u=len(unknown)
        output.append({'leverage':lev,'verified_events':n,'verified_wins':wins,'verified_win_rate_pct':100*wins/n if n else None,
          'mean_net_pct_notional':float(100*x.mean()) if n else None,'profit_factor':pos/neg if neg else None,
          'possible_unknown_events':u,'unit_win_rate_upper_pct':100*(wins+u)/(n+u) if n+u else None,
          'known_no_order_events':noorder,'passes_sample_size':n>=50,'screen_complete':u==0,
          'screen_pass':bool(u==0 and n>=50 and wins/n>.60 and x.mean()>0 and neg>0 and pos/neg>1),
          'verified_observation_ids':sorted(r['observation_id'] for r in good),'unknown_observation_ids':sorted(unknown)})
        assert n+u+noorder==len(events)
    out={'period':'2024-01-01 to 2024-04-30 UTC with prior-quarter and embargo constraints',
         'market_status_counts':quality['market_status_counts'],'rows':output,
         'note':'Prior BTC/ETH bars only. Unknown PnL is not imputed; this is not shared-account performance.'}
    (H/'双币活跃度训练诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DUAL40_TRAIN_DIAGNOSIS',json.dumps({**out,'rows':[{k:v for k,v in r.items() if not k.endswith('_observation_ids')} for r in output]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
