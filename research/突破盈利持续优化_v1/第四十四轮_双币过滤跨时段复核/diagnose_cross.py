"""Summarize verified unit opportunities and unresolved candidate bounds."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def main():
    f=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((H/'冻结研究方案.md').read_bytes()).hexdigest()==f['plan_sha256']
    decisions=pd.read_parquet(H/'候选事前市场过滤.parquet')
    source=pd.read_parquet(H/'冻结输入'/'baseline_signal.parquet')
    output=[]
    for period in ('2024_may_jun','2026_may_jul'):
        d=H/period;signal=source[source.research_period.eq(period)]
        s=signal.merge(decisions,on=['observation_id','quarter_start'],validate='one_to_one')
        ledger=pd.read_parquet(d/'动态池单位收益与风险.parquet')
        for lev in (10,20):
            v=ledger[ledger.variant.eq(f'normal_2r_{lev}x')]
            assert v.observation_id.is_unique
            byid={r['observation_id']:r for r in v.to_dict('records')}
            good=[];unknown=set();noorder=0
            for e in s.to_dict('records'):
                obs=e['observation_id'];market=e['market_status'];side=int(e['allowed_side']);status=e['status']
                if market=='known_no_order':noorder+=1;continue
                if status not in BENIGN:
                    possible=(market=='market_unknown' or side==1 and bool(e['long_known_eligible']) or side==-1 and bool(e['short_known_eligible']))
                    if possible:unknown.add(obs)
                    else:noorder+=1
                    continue
                if status!='qualified':noorder+=1;continue
                pre=e.get(f'precheck_{lev}x')
                if pd.isna(pre):unknown.add(obs);continue
                if pre!='passed':noorder+=1;continue
                if market=='market_unknown':unknown.add(obs);continue
                if int(e['side'])!=side:noorder+=1;continue
                row=byid.get(obs)
                if not row or row['status']!='verified' or row['risk_status']!='verified' or row['liq_proxy']:
                    unknown.add(obs);continue
                assert int(row['entry_ts'])>=int(row['decision_ts'])+10_000
                good.append(row)
            n=len(good);u=len(unknown);x=np.asarray([r['net_per_unit_notional'] for r in good],float)
            assert np.isfinite(x).all() and n+u+noorder==len(s)
            w=int((x>0).sum());pos=float(x[x>0].sum());neg=float(-x[x<0].sum())
            days={pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for r in good}
            output.append({'period':period,'leverage':lev,'candidates':len(s),'known_no_order':noorder,
               'verified_events':n,'verified_wins':w,'verified_active_days_utc':len(days),
               'verified_win_rate_pct':100*w/n if n else None,'mean_net_pct_notional':100*float(x.mean()) if n else None,
               'profit_factor':pos/neg if neg else None,'possible_unknown_events':u,
               'unit_win_rate_lower_pct':100*w/(n+u) if n+u else None,
               'unit_win_rate_upper_pct':100*(w+u)/(n+u) if n+u else None,
               'screen_complete':u==0,'verified_observation_ids':sorted(r['observation_id'] for r in good),
               'unknown_observation_ids':sorted(unknown)})
    out={'rows':output,'note':'Retrospective, overlapping project samples; unit paths only, no unknown PnL imputation or shared account.'}
    (H/'跨时段双币过滤诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CROSS44_DIAGNOSIS',json.dumps([{k:v for k,v in r.items() if not k.endswith('_ids')} for r in output],ensure_ascii=False),flush=True)
if __name__=='__main__':main()
