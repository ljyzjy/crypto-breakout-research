"""Compare original and single-retest unit paths with explicit unknown cases."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent
ORIG_OK={'first_direction_ineligible','no_order_time','flow_filter_not_met','known_risk_rejected','qualified'}
RETRY_OK={'no_retest_known','retest_flow_filter_not_met','no_order_time','known_risk_rejected','qualified'}
def read_paths(file):return pd.read_parquet(file) if file.exists() else pd.DataFrame()
def main():
    output=[];capture=[]
    years=('2023',) if '--2023-only' in sys.argv else ('2023','2024','2026')
    for year in years:
        inp=H/('2023冻结输入' if year=='2023' else '跨期冻结输入')
        signal=pd.read_parquet(inp/('baseline_signal.parquet' if year=='2023' else f'{year}_signal.parquet'))
        paths=pd.read_parquet(inp/('baseline_paths.parquet' if year=='2023' else f'{year}_paths.parquet'))
        ledger=pd.read_parquet(inp/('baseline_ledger.parquet' if year=='2023' else f'{year}_ledger.parquet'))
        retry=H/f'{year}重试分批';rs=pd.read_parquet(retry/'动态池逐笔信号筛查.parquet')
        rp=read_paths(retry/'动态池延迟市价路径.parquet');rl=read_paths(retry/'动态池单位收益与风险.parquet')
        assert signal.observation_id.is_unique and rs.observation_id.is_unique
        retries={r['observation_id']:r for r in rs.to_dict('records')}
        for lev in (10,20):
            variant=f'normal_2r_{lev}x'
            def lookup(frame):return {r['observation_id']:r for r in frame[frame.variant.eq(variant)].to_dict('records')} if len(frame) else {}
            op,ol,nptr,nled=lookup(paths),lookup(ledger),lookup(rp),lookup(rl)
            for strategy in ('baseline','single_retest'):
                good={};unknown=set();noorder=0;added=0
                for e in signal.to_dict('records'):
                    obs=e['observation_id'];is_retry=strategy=='single_retest' and obs in retries
                    row=retries[obs] if is_retry else e;allowed=RETRY_OK if is_retry else ORIG_OK
                    pathmap=nptr if is_retry else op;ledgermap=nled if is_retry else ol
                    if row['status'] not in allowed:unknown.add(obs);continue
                    if row['status']!='qualified':noorder+=1;continue
                    pre=row.get(f'precheck_{lev}x')
                    if pd.isna(pre):unknown.add(obs);continue
                    if pre!='passed':noorder+=1;continue
                    pp=pathmap.get(obs);r=ledgermap.get(obs)
                    if pp is None or pp['status']!='verified' or r is None or r['risk_status']!='verified' or r['liq_proxy']:
                        unknown.add(obs);continue
                    assert int(r['entry_ts'])>=int(r['decision_ts'])+10_000
                    good[obs]=r;added+=int(is_retry)
                n=len(good);u=len(unknown);vals=np.array([r['net_per_unit_notional'] for r in good.values()],float);assert np.isfinite(vals).all()
                w=int((vals>0).sum());pos=float(vals[vals>0].sum());neg=float(-vals[vals<0].sum());assert n+u+noorder==len(signal)
                days={pd.Timestamp(int(r['entry_ts']),unit='ms',tz='UTC').strftime('%Y-%m-%d') for r in good.values()}
                output.append({'year':year,'strategy':strategy,'leverage':lev,'candidates':len(signal),'known_no_order':noorder,
                    'verified_events':n,'verified_wins':w,'verified_active_days_utc':len(days),'verified_added_retest_entries':added,
                    'verified_win_rate_pct':100*w/n if n else None,'mean_net_pct_notional':100*float(vals.mean()) if n else None,
                    'profit_factor':pos/neg if neg else None,'possible_unknown_events':u,
                    'unit_win_rate_lower_pct':100*w/(n+u) if n+u else None,'unit_win_rate_upper_pct':100*(w+u)/(n+u) if n+u else None,
                    'verified_observation_ids':sorted(good),'unknown_observation_ids':sorted(unknown)})
                if year=='2023':
                    labels=pd.read_parquet(inp/'postclose_labels.parquet').set_index('observation_id')
                    candidates=pd.read_parquet(inp/'candidates.parquet').set_index('observation_id')
                    large={obs for obs,z in labels.iterrows() if z.status=='verified' and bool(z.large)}
                    captured={obs for obs,r in good.items() if obs in large and int(r['side'])==int(labels.loc[obs,'allowed_side']) and int(r['entry_ts'])<int(candidates.loc[obs,'quarter_end'])}
                    possible=large&unknown
                    capture.append({'strategy':strategy,'leverage':lev,'known_large_candidates':len(large),
                         'verified_captures':len(captured),'unknown_large_candidates':len(possible),
                         'capture_pct_within_known_candidates':100*len(captured)/len(large) if large else None,
                         'optimistic_capture_pct_within_known_candidates':100*(len(captured)+len(possible))/len(large) if large else None,
                         'captured_observation_ids':sorted(captured),'unknown_large_observation_ids':sorted(possible)})
    out={'rows':output,'postclose_2023_capture':capture,
         'note':'Unit opportunities only; post-close candle labels were not used to enter, unknown PnL is not filled.'}
    name='2023单次重试单位对照.json' if '--2023-only' in sys.argv else '单次重试跨期单位对照.json'
    (H/name).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RETEST47_COMPARISON',json.dumps({'rows':[{k:v for k,v in r.items() if not k.endswith('_ids')} for r in output],
         'capture':[{k:v for k,v in r.items() if not k.endswith('_ids')} for r in capture]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
