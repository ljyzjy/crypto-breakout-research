"""Evaluate one frozen five-second price-extension threshold."""
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;I=H/'冻结输入'
ORIG={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
RETRY={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def index(d,v):return {x['observation_id']:x for x in d[d.variant.eq(v)].to_dict('records')}
def main():
    f=json.loads((H/'输入冻结哈希.json').read_text(encoding='utf-8'));assert sha(H/'冻结研究方案.md')==f['plan_sha256']
    for n,v in f['inputs'].items():assert sha(I/n)==v
    rows=[];details=[]
    for year in ('2023','2024','2026'):
        base=pd.read_parquet(I/f'{year}_baseline_signal.parquet');retry=pd.read_parquet(I/f'{year}_retry_signal.parquet')
        op=pd.read_parquet(I/f'{year}_baseline_paths.parquet');ol=pd.read_parquet(I/f'{year}_baseline_ledger.parquet')
        rp=pd.read_parquet(I/f'{year}_retry_paths.parquet');rl=pd.read_parquet(I/f'{year}_retry_ledger.parquet')
        rd={x['observation_id']:x for x in retry.to_dict('records')};assert base.observation_id.is_unique and len(rd)==len(retry)
        for lev in (10,20):
            variant=f'normal_2r_{lev}x';om=index(op,variant);og=index(ol,variant);rm=index(rp,variant);rg=index(rl,variant)
            for mode in ('original','extension_005pct'):
                good={};unknown=set();noorder=0;rejected=0
                for old in base.to_dict('records'):
                    obs=old['observation_id'];isretry=obs in rd;e=rd.get(obs,old);allowed=RETRY if isretry else ORIG
                    if e['status'] not in allowed:unknown.add(obs);continue
                    if e['status']!='qualified':noorder+=1;continue
                    px=float(e['signal_close']);ref=float(e['raw_entry_5s']);side=int(e['side'])
                    assert np.isfinite(px) and np.isfinite(ref) and px>0 and ref>0 and side in (-1,1)
                    assert int(e['entry_exec_ts'])>=int(e['decision_ts'])+5000
                    extension=side*(ref/px-1)
                    if mode=='extension_005pct' and extension<.0005:noorder+=1;rejected+=1;continue
                    pre=e[f'precheck_{lev}x']
                    if pd.isna(pre):unknown.add(obs);continue
                    if pre!='passed':noorder+=1;continue
                    path=(rm if isretry else om).get(obs);ledger=(rg if isretry else og).get(obs)
                    if path is None or path['status']!='verified' or ledger is None or ledger['risk_status']!='verified' or ledger['liq_proxy']:
                        unknown.add(obs);continue
                    assert int(ledger['entry_ts'])>=int(e['decision_ts'])+10000;good[obs]=ledger
                    if mode=='extension_005pct':details.append({'year':year,'leverage':lev,'observation_id':obs,
                         'extension':extension,'entry_origin':'retest' if isretry else 'original','net':ledger['net_per_unit_notional']})
                n=len(good);u=len(unknown);x=np.asarray([r['net_per_unit_notional'] for r in good.values()],float);assert np.isfinite(x).all()
                win=int((x>0).sum());pos=float(x[x>0].sum());neg=float(-x[x<0].sum());assert n+u+noorder==len(base)
                days={pd.Timestamp(int(z['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for z in good.values()}
                rows.append({'year':year,'leverage':lev,'strategy':mode,'candidate_events':len(base),'known_no_order':noorder,
                    'qualified_rejected_by_extension':rejected,'verified_events':n,'verified_wins':win,'active_days_utc':len(days),
                    'net_win_rate_pct':100*win/n if n else None,'mean_net_pct_notional':100*float(x.mean()) if n else None,
                    'profit_factor':pos/neg if neg else None,'possible_unknown_events':u,
                    'optimistic_unit_win_upper_pct':100*(win+u)/(n+u) if n+u else None,'verified_ids':sorted(good),'unknown_ids':sorted(unknown)})
    pd.DataFrame(details).to_parquet(H/'价格延伸已核验明细.parquet',index=False)
    out={'rows':rows,'note':'Cost-anchored pre-entry filter on verified unit opportunities; unknowns preserved.'}
    (H/'价格延伸跨期单位对照.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PRICE50_COMPARISON',json.dumps({'rows':[{k:v for k,v in x.items() if not k.endswith('_ids')} for x in rows]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
