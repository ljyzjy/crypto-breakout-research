"""Compare one pre-fixed causal flow threshold on verified unit paths."""
import hashlib,json,math
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
ORIG={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
RETRY={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def index(d,v):return {r['observation_id']:r for r in d[d.variant.eq(v)].to_dict('records')}
def main():
    f=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    results=[];details=[]
    for year in ('2023','2024','2026'):
        s=pd.read_parquet(I/f'{year}_baseline_signal.parquet');r=pd.read_parquet(I/f'{year}_retry_signal.parquet')
        op=pd.read_parquet(I/f'{year}_baseline_paths.parquet');ol=pd.read_parquet(I/f'{year}_baseline_ledger.parquet')
        rp=pd.read_parquet(I/f'{year}_retry_paths.parquet');rl=pd.read_parquet(I/f'{year}_retry_ledger.parquet')
        retry={x['observation_id']:x for x in r.to_dict('records')};assert s.observation_id.is_unique and len(retry)==len(r)
        for lev in (10,20):
            v=f'normal_2r_{lev}x';om=index(op,v);og=index(ol,v);rm=index(rp,v);rg=index(rl,v)
            for mode in ('original_010','strong_030'):
                good={};unknown=set();noorder=0;blocked=0
                for orig in s.to_dict('records'):
                    obs=orig['observation_id'];isretry=obs in retry;e=retry.get(obs,orig);allowed=RETRY if isretry else ORIG
                    if e['status'] not in allowed:unknown.add(obs);continue
                    if e['status']!='qualified':noorder+=1;continue
                    buy=float(e['buy_notional']);sell=float(e['sell_notional']);flow=float(e['five_imbalance'])
                    assert buy>=0 and sell>=0 and buy+sell>0 and int(e['five_count'])>=3
                    assert math.isclose(flow,int(e['side'])*(buy-sell)/(buy+sell),rel_tol=1e-10,abs_tol=1e-10)
                    assert flow>=.10-1e-10 and int(e['entry_exec_ts'])>=int(e['decision_ts'])+5000
                    if mode=='strong_030' and flow<.30:noorder+=1;blocked+=1;continue
                    pre=e[f'precheck_{lev}x']
                    if pd.isna(pre):unknown.add(obs);continue
                    if pre!='passed':noorder+=1;continue
                    path=(rm if isretry else om).get(obs);ledger=(rg if isretry else og).get(obs)
                    if path is None or path['status']!='verified' or ledger is None or ledger['risk_status']!='verified' or ledger['liq_proxy']:
                        unknown.add(obs);continue
                    assert int(ledger['entry_ts'])>=int(e['decision_ts'])+10000
                    good[obs]=ledger
                    if mode=='strong_030':details.append({'year':year,'leverage':lev,'observation_id':obs,'flow':flow,
                                                         'entry_origin':'retest' if isretry else 'original','net':ledger['net_per_unit_notional']})
                n=len(good);u=len(unknown);values=np.asarray([x['net_per_unit_notional'] for x in good.values()],float);assert np.isfinite(values).all()
                win=int((values>0).sum());pos=float(values[values>0].sum());neg=float(-values[values<0].sum())
                days={pd.Timestamp(int(x['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for x in good.values()}
                assert n+u+noorder==len(s)
                results.append({'year':year,'leverage':lev,'strategy':mode,'candidate_events':len(s),'known_no_order':noorder,
                   'qualified_rejected_by_flow':blocked,'verified_events':n,'verified_wins':win,'active_days_utc':len(days),
                   'net_win_rate_pct':100*win/n if n else None,'mean_net_pct_notional':100*float(values.mean()) if n else None,
                   'profit_factor':pos/neg if neg else None,'possible_unknown_events':u,
                   'optimistic_unit_win_upper_pct':100*(win+u)/(n+u) if n+u else None,
                   'verified_ids':sorted(good),'unknown_ids':sorted(unknown)})
    pd.DataFrame(details).to_parquet(H/'强方向筛选已核验明细.parquet',index=False)
    z={'rows':results,'note':'Known unit paths with fixed pre-entry threshold; no shared-account or prospective result.'}
    (H/'强方向跨期单位对照.json').write_text(json.dumps(z,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FLOW49_COMPARISON',json.dumps({'rows':[{k:v for k,v in x.items() if not k.endswith('_ids')} for x in results]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
