"""Compare one- and five-second execution assumptions on matched candidates."""
import json,math,sys
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
ORIG={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
RETRY={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
def index(d,v):return {x['observation_id']:x for x in d[d.variant.eq(v)].to_dict('records')}
def stats(values):
    x=np.asarray(values,float);assert np.isfinite(x).all();n=len(x);w=int((x>0).sum());a=float(x[x>0].sum());b=float(-x[x<0].sum())
    return {'trades':n,'wins':w,'net_win_rate_pct':100*w/n if n else None,'mean_net_pct_notional':100*float(x.mean()) if n else None,
            'sum_net_pct_equal_notional':100*float(x.sum()),'profit_factor':a/b if b else None}
def main(year):
    I=H/f'{year}冻结输入';B=H/f'{year}一秒入场分批';base=pd.read_parquet(I/'baseline_signal.parquet');retry=pd.read_parquet(I/'retry_signal.parquet')
    rd={x['observation_id']:x for x in retry.to_dict('records')};assert len(rd)==len(retry)
    old=pd.concat([pd.read_parquet(I/'baseline_ledger.parquet'),pd.read_parquet(I/'retry_ledger.parquet')],ignore_index=True)
    new=pd.read_parquet(B/'动态池单位收益与风险.parquet');out=[];details=[]
    for lev in (10,20):
        oldi=index(old,f'normal_2r_{lev}x');newi=index(new,f'one_second_2r_{lev}x');both=[];unknown=[];noorder=0
        for original in base.to_dict('records'):
            obs=original['observation_id'];e=rd.get(obs,original);allowed=RETRY if obs in rd else ORIG
            if e['status'] not in allowed:unknown.append(obs);continue
            if e['status']!='qualified':noorder+=1;continue
            pre=e[f'precheck_{lev}x']
            if pd.isna(pre):unknown.append(obs);continue
            if pre!='passed':noorder+=1;continue
            a,b=oldi.get(obs),newi.get(obs)
            if a is None or b is None or a['risk_status']!='verified' or b['risk_status']!='verified' or a['liq_proxy'] or b['liq_proxy']:
                unknown.append(obs);continue
            assert math.isclose(float(a['initial_stop']),float(b['initial_stop']),rel_tol=1e-11,abs_tol=1e-11)
            assert int(b['entry_ts'])>=int(e['entry_exec_ts'])+1000 and int(a['entry_ts'])>=int(e['entry_exec_ts'])+5000
            assert int(b['entry_ts'])<=int(a['entry_ts']);both.append((obs,a,b))
            details.append({'observation_id':obs,'leverage':lev,'one_second_net':float(b['net_per_unit_notional']),
                            'five_second_net':float(a['net_per_unit_notional']),'one_second_reason':b['reason'],
                            'five_second_reason':a['reason'],'one_second_entry_ts':int(b['entry_ts']),'five_second_entry_ts':int(a['entry_ts'])})
        assert len(both)+len(unknown)+noorder==len(base)
        one=[float(b['net_per_unit_notional']) for _,a,b in both];five=[float(a['net_per_unit_notional']) for _,a,b in both]
        s1=stats(one);s5=stats(five);diff=np.asarray(one)-np.asarray(five);n=len(both);u=len(unknown)
        days={pd.Timestamp(int(b['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for _,a,b in both}
        for x in (s1,s5):x['optimistic_unit_win_upper_pct']=100*(x['wins']+u)/(n+u) if n+u else None
        out.append({'leverage':lev,'candidate_events':len(base),'known_no_order':noorder,'paired_verified':n,'paired_unknown':u,
                    'active_days_utc':len(days),'one_second':s1,'five_second':s5,'mean_one_minus_five_pct_notional':100*float(diff.mean()) if n else None,
                    'one_second_better_count':int((diff>1e-12).sum()),'one_second_worse_count':int((diff< -1e-12).sum()),
                    'same_count':int((np.abs(diff)<=1e-12).sum()),'unknown_ids':sorted(unknown)})
    pd.DataFrame(details).to_parquet(H/f'{year}一秒五秒逐笔配对结果.parquet',index=False)
    out={'year':year,'rows':out,'note':'Same original qualified candidates, prechecks and equal-entry-notional unit scoring; not an account.'}
    (H/f'{year}一秒五秒配对对照.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENTRY51_PAIRED',year,json.dumps({'rows':[{k:v for k,v in x.items() if k!='unknown_ids'} for x in out['rows']]},ensure_ascii=False),flush=True)
if __name__=='__main__':
    assert len(sys.argv)==2 and sys.argv[1] in ('2023','2024','2026');main(sys.argv[1])
