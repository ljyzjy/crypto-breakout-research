"""Strictly paired 1R and 2R evaluation with explicit unknown candidates."""
import json, math
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'2023冻结输入';B=H/'2023一倍止盈分批'
ORIG={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
RETRY={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
def index(d,v):return {x['observation_id']:x for x in d[d.variant.eq(v)].to_dict('records')}
def stats(vals):
    x=np.asarray(vals,dtype=float);assert np.isfinite(x).all()
    n=len(x);win=int((x>0).sum());pos=float(x[x>0].sum());neg=float(-x[x<0].sum())
    return {'trades':n,'wins':win,'net_win_rate_pct':100*win/n if n else None,
            'mean_net_pct_notional':100*float(x.mean()) if n else None,
            'sum_net_pct_equal_notional':100*float(x.sum()),'profit_factor':pos/neg if neg else None}
def main():
    base=pd.read_parquet(I/'baseline_signal.parquet');retry=pd.read_parquet(I/'retry_signal.parquet')
    retry_by={x['observation_id']:x for x in retry.to_dict('records')};assert len(retry_by)==len(retry)
    old=pd.concat([pd.read_parquet(I/'baseline_ledger.parquet'),pd.read_parquet(I/'retry_ledger.parquet')],ignore_index=True)
    new=pd.read_parquet(B/'动态池单位收益与风险.parquet');out=[];paired_detail=[]
    for lev in (10,20):
        oldi=index(old,f'normal_2r_{lev}x');newi=index(new,f'normal_1r_{lev}x')
        both=[];unknown=[];noorder=0
        for original in base.to_dict('records'):
            obs=original['observation_id'];e=retry_by.get(obs,original);allowed=RETRY if obs in retry_by else ORIG
            if e['status'] not in allowed:unknown.append(obs);continue
            if e['status']!='qualified':noorder+=1;continue
            pre=e[f'precheck_{lev}x']
            if pd.isna(pre):unknown.append(obs);continue
            if pre!='passed':noorder+=1;continue
            a,b=oldi.get(obs),newi.get(obs)
            if a is None or b is None or a['risk_status']!='verified' or b['risk_status']!='verified' or a['liq_proxy'] or b['liq_proxy']:
                unknown.append(obs);continue
            for k in ('entry_ts','entry_raw','entry_fill','initial_stop'):
                assert math.isclose(float(a[k]),float(b[k]),rel_tol=1e-11,abs_tol=1e-11),(obs,k)
            assert int(b['exit_signal_ts'])<=int(a['exit_signal_ts'])
            both.append((obs,a,b))
            paired_detail.append({'observation_id':obs,'leverage':lev,'one_r_net':float(b['net_per_unit_notional']),
                 'two_r_net':float(a['net_per_unit_notional']),'one_r_reason':b['reason'],'two_r_reason':a['reason']})
        assert len(both)+len(unknown)+noorder==len(base)
        vals1=[float(b['net_per_unit_notional']) for _,a,b in both];vals2=[float(a['net_per_unit_notional']) for _,a,b in both]
        s1=stats(vals1);s2=stats(vals2);diff=np.asarray(vals1)-np.asarray(vals2);n=len(both);u=len(unknown)
        days={pd.Timestamp(int(b['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for _,a,b in both}
        for x in (s1,s2):x['optimistic_unit_win_upper_pct']=100*(x['wins']+u)/(n+u) if n+u else None
        out.append({'leverage':lev,'candidate_events':len(base),'known_no_order':noorder,'paired_verified':n,'paired_unknown':u,
              'active_days_utc':len(days),'one_r':s1,'two_r':s2,'mean_1r_minus_2r_pct_notional':100*float(diff.mean()) if n else None,
              'one_r_better_count':int((diff>1e-12).sum()),'one_r_worse_count':int((diff< -1e-12).sum()),
              'same_count':int((np.abs(diff)<=1e-12).sum()),'unknown_ids':sorted(unknown)})
    pd.DataFrame(paired_detail).to_parquet(H/'2023一倍两倍逐笔配对结果.parquet',index=False)
    result={'year':'2023','rows':out,'note':'Only matched verified entries and risk paths; unknowns are retained. Unit opportunities, not a shared account.'}
    (H/'2023一倍两倍配对对照.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('EXIT1R48_2023_PAIRED',json.dumps({'rows':[{k:v for k,v in z.items() if k!='unknown_ids'} for z in out]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
