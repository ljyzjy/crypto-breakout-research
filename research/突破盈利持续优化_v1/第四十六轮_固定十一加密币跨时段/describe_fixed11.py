"""Count fixed-pool known paths and explicit unknown bounds per leverage."""
import json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
BENIGN={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
def main():
    output=[]
    for year in ('2024','2026'):
        folder=H/year/'逐笔分批';s=pd.read_parquet(folder/'动态池逐笔信号筛查.parquet');p=pd.read_parquet(folder/'动态池延迟市价路径.parquet')
        ledgerfile=folder/'动态池单位收益与风险.parquet';ledger=pd.read_parquet(ledgerfile) if ledgerfile.exists() else pd.DataFrame()
        assert s.observation_id.is_unique
        for lev in (10,20):
            variant=f'normal_2r_{lev}x';paths=p[p.variant.eq(variant)] if len(p) else p
            settled=ledger[ledger.variant.eq(variant)] if len(ledger) else ledger
            if len(paths):assert paths.observation_id.is_unique
            if len(settled):assert settled.observation_id.is_unique
            bypath={r['observation_id']:r for r in paths.to_dict('records')};byledger={r['observation_id']:r for r in settled.to_dict('records')}
            good=[];unknown=set();noorder=0
            for e in s.to_dict('records'):
                obs=e['observation_id'];status=e['status']
                if status not in BENIGN:unknown.add(obs);continue
                if status!='qualified':noorder+=1;continue
                pre=e.get(f'precheck_{lev}x')
                if pd.isna(pre):unknown.add(obs);continue
                if pre!='passed':noorder+=1;continue
                pp=bypath.get(obs);r=byledger.get(obs)
                if not pp or pp['status']!='verified' or not r or r['risk_status']!='verified' or r['liq_proxy']:
                    unknown.add(obs);continue
                assert int(r['entry_ts'])>=int(r['decision_ts'])+10_000
                good.append(r)
            n=len(good);u=len(unknown);x=np.asarray([r['net_per_unit_notional'] for r in good],float);assert np.isfinite(x).all()
            wins=int((x>0).sum());pos=float(x[x>0].sum());neg=float(-x[x<0].sum());assert n+u+noorder==len(s)
            days={pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for r in good}
            output.append({'period':year,'leverage':lev,'candidate_events':len(s),'known_no_order':noorder,
                 'verified_events':n,'verified_wins':wins,'verified_active_days_utc':len(days),
                 'verified_win_rate_pct':100*wins/n if n else None,'mean_net_pct_notional':100*float(x.mean()) if n else None,
                 'profit_factor':pos/neg if neg else None,'possible_unknown_events':u,
                 'unit_win_rate_lower_pct':100*wins/(n+u) if n+u else None,'unit_win_rate_upper_pct':100*(wins+u)/(n+u) if n+u else None,
                 'verified_observation_ids':sorted(r['observation_id'] for r in good),'unknown_observation_ids':sorted(unknown)})
    out={'rows':output,'note':'Known independent unit opportunities only; unknown PnL is not assigned, and account trading is not simulated.'}
    (H/'固定十一币跨期单位诊断.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FIXED11_46_DIAGNOSIS',json.dumps([{k:v for k,v in r.items() if not k.endswith('_ids')} for r in output],ensure_ascii=False),flush=True)
if __name__=='__main__':main()
